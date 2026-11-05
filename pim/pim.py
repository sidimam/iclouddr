#!/usr/bin/env python3
"""Modulo PIM di iclouddr (sidimam): note e promemoria da iCloud verso una cartella del NAS, in sola lettura.

Gira dentro il container iclouddr accanto al programma originale (mandarons/icloud-drive), che resta invariato.
- Sessione Apple: la stessa di iclouddr. Ogni giro ne fa una COPIA in /tmp e lavora su quella, così pyicloud non
  riscrive mai i file di sessione di iclouddr (/config/session_data). Nessun secondo 2FA.
- Note: CloudKit via pyicloud ≥ 2026.10 → <dest>/Note/<cartella>/<titolo>.html con le immagini e gli allegati accanto.
  Le note protette da password non si possono leggere e vengono solo elencate.
- Promemoria: CloudKit via pyicloud → <dest>/Promemoria/<lista>.json (tutti i campi) e <lista>.md (da leggere).
- Stato dell'ultimo giro in /config/pim-status.json (lo legge iCloud Dashboard).
- Account (dalla 0.2): posta, calendario e contatti di iCloud, Gmail, Outlook o altro IMAP, da /config/pim-accounts.json
  (lo scrive iCloud Dashboard), ognuno in <persona>/<etichetta>/ — vedi accounts_sync.py. Serve il mount /icloud/persona
  (la cartella della persona, es. /mnt/user/documents/Simone).
Variabili: PIM_DEST (default /icloud/pim), PIM_INTERVAL (note e promemoria, default 21600 s), PIM_MAIL_INTERVAL (900),
PIM_DAV_INTERVAL (calendari e contatti, 3600), PIM_ONCE=1 per un solo giro. Il file /config/pim-run-now fa ripartire subito tutto.
"""
import datetime, json, os, re, shutil, sys, tempfile, time, traceback

SRC_SESSION = os.environ.get("PIM_SESSION_DIR", "/config/session_data")
CONFIG = os.environ.get("ENV_CONFIG_FILE_PATH", "/config/config.yaml")
DEST = os.environ.get("PIM_DEST", "/icloud/pim")
STATUS = os.environ.get("PIM_STATUS", "/config/pim-status.json")
INTERVAL = int(os.environ.get("PIM_INTERVAL", "21600"))
MAIL_INTERVAL = int(os.environ.get("PIM_MAIL_INTERVAL", "900"))
DAV_INTERVAL = int(os.environ.get("PIM_DAV_INTERVAL", "3600"))
PERSON = os.environ.get("PIM_PERSON", "/icloud/persona")
RUN_NOW = os.environ.get("PIM_RUN_NOW", "/config/pim-run-now")


def log(msg):
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} :: PIM :: {msg}", flush=True)


def safe(name, fallback="senza titolo"):
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (name or "").strip()).strip(" .")
    return (n or fallback)[:120]


def username():
    m = re.search(r'username:\s*"?([^"\n]+)"?', open(CONFIG).read())
    if not m:
        raise SystemExit("PIM: username non trovato in config.yaml")
    return m.group(1).strip()


def session_copy(user):
    """Copia la sessione di iclouddr in una cartella temporanea, con i nomi di file che si aspetta pyicloud."""
    work = tempfile.mkdtemp(prefix="pim-session-")
    for f in os.listdir(SRC_SESSION):
        shutil.copy2(os.path.join(SRC_SESSION, f), os.path.join(work, f))
    base = "".join(c for c in user if re.match(r"\w", c))
    if os.path.exists(os.path.join(work, base)) and not os.path.exists(os.path.join(work, base + ".cookiejar")):
        shutil.copy2(os.path.join(work, base), os.path.join(work, base + ".cookiejar"))
    return work


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def export_notes(api, dest, shared=(set(), set())):
    out = os.path.join(dest, "Note")
    stage = tempfile.mkdtemp(prefix="pim-note-", dir=dest)
    os.chmod(stage, 0o777)   # mkdtemp crea 0700: con i permessi di Unraid la cartella si apre anche dalle share
    n = api.notes
    index, locked, failed = [], [], []
    notes = [x for x in n.iter_all() if not getattr(x, "is_deleted", False)]
    # Titoli ripetuti nella stessa cartella: l'esportatore li scriverebbe nello stesso file, uno sopra l'altro.
    # Quelle note prendono subito un nome con l'inizio del loro identificativo.
    seen_names = {}
    for x in notes:
        k = (safe(getattr(x, "folder_name", None), "Note"), safe(getattr(x, "title", None)).lower())
        seen_names[k] = seen_names.get(k, 0) + 1
    for s in notes:
        folder = safe(getattr(s, "folder_name", None), "Note")
        title = safe(getattr(s, "title", None))
        entry = {"id": s.id, "title": getattr(s, "title", None), "folder": folder,
                 "modified": str(getattr(s, "modified_at", getattr(s, "modification_date", "")) or "")}
        if s.id in shared[0] or getattr(s, "folder_id", None) in shared[1]:
            entry["shared"] = True
        if getattr(s, "is_locked", False):
            locked.append(entry)
            continue
        try:
            fdir = os.path.join(stage, folder)
            os.makedirs(fdir, exist_ok=True)
            p = n.export_note(s.id, fdir, export_mode="archival", assets_dir=os.path.join(fdir, "_allegati"))
            dup = seen_names.get((folder, title.lower()), 0) > 1
            want = os.path.join(fdir, f"{title} ({s.id[:8]}).html" if dup else title + ".html")
            if os.path.abspath(p) != os.path.abspath(want):
                if os.path.exists(want) and not dup:
                    want = os.path.join(fdir, f"{title} ({s.id[:8]}).html")
                os.replace(p, want)
            entry["file"] = os.path.relpath(want, stage)
            index.append(entry)
        except Exception as e:
            failed.append({**entry, "error": f"{type(e).__name__}: {str(e)[:200]}"})
    write_atomic(os.path.join(stage, "indice.json"), json.dumps({"note": index, "protette": locked, "errori": failed},
                                                               ensure_ascii=False, indent=1))
    # Sostituisce la cartella intera solo a giro riuscito: chi legge non vede mai un'esportazione a metà.
    old = out + ".old"
    if os.path.exists(old):
        shutil.rmtree(old)
    if os.path.exists(out):
        os.replace(out, old)
    os.replace(stage, out)
    shutil.rmtree(old, ignore_errors=True)
    return {"note": len(index), "protette": len(locked), "errori": len(failed),
            "condivise": [e["file"] for e in index if e.get("shared")]}


def retry(fn, *a, tries=6, **kw):
    """CloudKit a volte risponde TRY_AGAIN_LATER (per esempio «Indexing scheduled» alla prima lettura di un account):
    aspetta il retryAfter indicato da Apple e riprova."""
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            txt = str(e)
            if "TRY_AGAIN_LATER" not in txt or i == tries - 1:
                raise
            m = re.search(r'"retryAfter"\s*:\s*(\d+)', txt)
            wait = min(int(m.group(1)) if m else 30, 300) + 5
            log(f"CloudKit chiede di riprovare tra {wait} s ({i + 1}/{tries})")
            time.sleep(wait)


def _fmt(ts):
    if ts in (None, "", 0):
        return ""
    try:
        if isinstance(ts, (int, float)):
            d = datetime.datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts)
        else:
            d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone()
        return d.strftime("%d/%m/%Y") if (d.hour, d.minute) == (0, 0) or (d.hour, d.minute) == (1, 0) else d.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(ts)


def export_reminders(api, dest, shared=set()):
    out = os.path.join(dest, "Promemoria")
    os.makedirs(out, exist_ok=True)
    r = api.reminders
    lists = retry(lambda: list(r.lists()))
    total, done = 0, set()
    for l in lists:
        title = getattr(l, "title", None) or getattr(l, "name", None) or l.id
        items = retry(lambda: list(r.reminders(l.id)))
        rows = []
        for it in items:
            d = it.model_dump(mode="json") if hasattr(it, "model_dump") else dict(it)
            # avvisi, tag e ripetizioni costano una richiesta l'uno: solo per i promemoria ancora da fare
            for k, fn in () if d.get("completed") else (("avvisi", r.alarms_for), ("tag", r.tags_for), ("ripetizioni", r.recurrence_rules_for)):
                try:
                    d[k] = [x.model_dump(mode="json") if hasattr(x, "model_dump") else str(x) for x in fn(it)]
                except Exception:
                    pass
            rows.append(d)
        total += len(rows)
        name = safe(title, "Lista")
        done.add(name)
        write_atomic(os.path.join(out, name + ".json"), json.dumps({"lista": title, "id": l.id, "condivisa": l.id in shared, "promemoria": rows},
                                                                   ensure_ascii=False, indent=1))
        md = [f"# {title}", ""]
        for d in sorted(rows, key=lambda x: (bool(x.get("completed")), str(x.get("due_date") or ""))):
            box = "x" if d.get("completed") else " "
            due = _fmt(d.get("due_date"))
            line = f"- [{box}] {d.get('title') or ''}" + (f" — scadenza {due}" if due else "")
            md.append(line)
            if d.get("desc"):
                md.append("  " + str(d["desc"]).replace("\n", "\n  "))
        write_atomic(os.path.join(out, name + ".md"), "\n".join(md) + "\n")
    for f in os.listdir(out):   # liste cancellate su iCloud
        if os.path.splitext(f)[0] not in done and f.endswith((".json", ".md")):
            os.remove(os.path.join(out, f))
    return {"liste": len(lists), "promemoria": total, "condivise": [getattr(l, "title", None) or l.id for l in lists if l.id in shared]}


def load_status():
    try:
        return json.load(open(STATUS))
    except (FileNotFoundError, ValueError):
        return {}


def save_status(st):
    try:
        write_atomic(STATUS, json.dumps(st, ensure_ascii=False, indent=1))
    except Exception:
        pass


FOLDERS = {"icloud": "iCloud", "gmail": "Gmail", "outlook": "Outlook"}


def account_dir(acc):
    """Cartella dell'account: quella scelta da iCloud Dashboard (campo folder), altrimenti il nome del servizio
    (iCloud, Gmail, Outlook), altrimenti l'etichetta. L'account iCloud scrive accanto a Note e Promemoria."""
    label = safe(acc.get("folder") or FOLDERS.get(acc.get("type")) or acc.get("label") or "Account", "Account")
    if os.path.isdir(PERSON):
        return os.path.join(PERSON, label)
    if acc.get("type") == "icloud":
        return DEST   # senza il mount della persona l'account iCloud scrive accanto a note e promemoria
    raise RuntimeError("manca il mount /icloud/persona (la cartella della persona)")


def run_account(acc, what):
    """what: insieme di "mail", "dav". Aggiorna la voce dell'account in pim-status.json."""
    import accounts_sync as A
    st = load_status()
    rec = st.setdefault("accounts", {}).setdefault(acc["id"], {})
    rec.update(label=acc.get("label"), type=acc.get("type"), email=acc.get("email"))
    # stato «in corso» subito, senza l'errore del giro precedente: la prima copia della posta può durare ore
    rec["running"] = {"what": sorted(what), "since": time.time()}; rec.pop("error", None)
    st.setdefault("accounts", {})[acc["id"]] = rec; save_status(st)
    try:
        base = account_dir(acc)
        rec["dir"] = base
        if "mail" in what and acc.get("mail"):
            t = time.time(); rec["mail"] = {**A.sync_mail(acc, base, log), "when": time.time(), "seconds": round(time.time() - t), "ok": True}
            log(f"{acc.get('label')}: posta {rec['mail']}")
        if "dav" in what and (acc.get("calendar") or acc.get("ics")):
            t = time.time(); rec["calendar"] = {**A.sync_calendar(acc, base), "when": time.time(), "seconds": round(time.time() - t), "ok": True}
            log(f"{acc.get('label')}: calendario {rec['calendar']}")
        if "dav" in what and acc.get("contacts"):
            t = time.time(); rec["contacts"] = {**A.sync_contacts(acc, base), "when": time.time(), "seconds": round(time.time() - t), "ok": True}
            log(f"{acc.get('label')}: contatti {rec['contacts']}")
        rec.pop("error", None)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        rec["error_when"] = time.time()
        log(f"{acc.get('label')}: ERRORE {rec['error']}")
    rec.pop("running", None)
    st2 = load_status(); st2.setdefault("accounts", {})[acc["id"]] = rec
    known = {a["id"] for a in __import__("accounts_sync").load()}
    st2["accounts"] = {k: v for k, v in st2["accounts"].items() if k in known}
    save_status(st2)


def shared_items(api):
    """Cosa è condiviso (vedi condivisi.py). Un errore qui non ferma l'esportazione: si perde solo il colore."""
    import condivisi as C
    out = {}
    for key, fn in (("note", C.notes), ("liste", C.lists), ("drive", C.drive)):
        try:
            v = retry(fn, api)
            if key == "note":
                out["_note_ids"], out["_folder_ids"] = v
            elif key == "liste":
                out["_list_ids"] = v
            else:
                out["drive"] = v
        except Exception as e:
            out.setdefault("errori", {})[key] = f"{type(e).__name__}: {str(e)[:200]}"
            log(f"condivisi ({key}): {out['errori'][key]}")
    return out


def run_once():
    from pyicloud import PyiCloudService
    started = time.time()
    status = {**load_status(), "started": started, "ok": False}
    status.pop("error", None)
    work = None
    try:
        user = username()
        work = session_copy(user)
        api = PyiCloudService(user, password=None, cookie_directory=work)
        if api.requires_2fa or getattr(api, "requires_2sa", False):
            raise RuntimeError("la sessione Apple chiede un nuovo 2FA: rinnovala da iCloud Dashboard (#nome auth)")
        os.makedirs(DEST, exist_ok=True)
        sh = shared_items(api)
        status["note"] = export_notes(api, DEST, (sh.pop("_note_ids", set()), sh.pop("_folder_ids", set())))
        log(f"note esportate: {status['note']}")
        status["promemoria"] = export_reminders(api, DEST, sh.pop("_list_ids", set()))
        sh.update(note=status["note"].pop("condivise", []), liste=status["promemoria"].pop("condivise", []), when=time.time())
        status["condivisi"] = sh
        log(f"promemoria esportati: {status['promemoria']}")
        status["ok"] = True
    except Exception as e:
        status["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        log("ERRORE " + status["error"])
        traceback.print_exc(limit=3)
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
        status["finished"] = time.time()
        status["seconds"] = round(status["finished"] - started)
        cur = load_status(); status["accounts"] = cur.get("accounts", status.get("accounts", {}))
        save_status(status)
    return status["ok"]


def main():
    os.umask(0)   # come «New Permissions» di Unraid: cartelle 777 e file 666, leggibili dalle share SMB
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import accounts_sync as A
    if os.environ.get("PIM_ONCE") == "1":
        ok = run_once()
        for acc in A.load():
            run_account(acc, {"mail", "dav"})
        sys.exit(0 if ok else 1)
    time.sleep(int(os.environ.get("PIM_START_DELAY", "120")))   # lascia partire prima iclouddr
    nxt = {"notes": 0}   # attività → prossimo orario
    while True:
        now = time.time()
        if os.path.exists(RUN_NOW):
            try: os.remove(RUN_NOW)
            except OSError: pass
            nxt = {k: 0 for k in nxt}; nxt["notes"] = 0
            log("sincronizzazione chiesta da iCloud Dashboard")
        if now >= nxt.get("notes", 0):
            run_once(); nxt["notes"] = time.time() + INTERVAL
        for acc in A.load():
            todo = set()
            if acc.get("mail") and time.time() >= nxt.get(acc["id"] + ":mail", 0): todo.add("mail")
            if (acc.get("calendar") or acc.get("contacts") or acc.get("ics")) and time.time() >= nxt.get(acc["id"] + ":dav", 0): todo.add("dav")
            if todo:
                run_account(acc, todo)
                if "mail" in todo: nxt[acc["id"] + ":mail"] = time.time() + MAIL_INTERVAL
                if "dav" in todo: nxt[acc["id"] + ":dav"] = time.time() + DAV_INTERVAL
        time.sleep(30)


if __name__ == "__main__":
    main()
