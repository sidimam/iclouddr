#!/usr/bin/env python3
"""Modulo PIM di iclouddr (sidimam): note e promemoria da iCloud verso una cartella del NAS, in sola lettura.

Gira dentro il container iclouddr accanto al programma originale (mandarons/icloud-drive), che resta invariato.
- Sessione Apple: la stessa di iclouddr. Ogni giro ne fa una COPIA in /tmp e lavora su quella, così pyicloud non
  riscrive mai i file di sessione di iclouddr (/config/session_data). Nessun secondo 2FA.
- Note: CloudKit via pyicloud ≥ 2026.10 → <dest>/Note/<cartella>/<titolo>.html con le immagini e gli allegati accanto.
  Le note protette da password non si possono leggere e vengono solo elencate.
- Promemoria: CloudKit via pyicloud → <dest>/Promemoria/<lista>.json (tutti i campi) e <lista>.md (da leggere).
- Stato dell'ultimo giro in /config/pim-status.json (lo legge iCloud Dashboard).
Variabili: PIM_DEST (default /icloud/pim), PIM_INTERVAL (secondi, default 21600), PIM_ONCE=1 per un solo giro.
"""
import datetime, json, os, re, shutil, sys, tempfile, time, traceback

SRC_SESSION = os.environ.get("PIM_SESSION_DIR", "/config/session_data")
CONFIG = os.environ.get("ENV_CONFIG_FILE_PATH", "/config/config.yaml")
DEST = os.environ.get("PIM_DEST", "/icloud/pim")
STATUS = os.environ.get("PIM_STATUS", "/config/pim-status.json")
INTERVAL = int(os.environ.get("PIM_INTERVAL", "21600"))


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


def export_notes(api, dest):
    out = os.path.join(dest, "Note")
    stage = tempfile.mkdtemp(prefix="pim-note-", dir=dest)
    os.chmod(stage, 0o777)   # mkdtemp crea 0700: con i permessi di Unraid la cartella si apre anche dalle share
    n = api.notes
    index, locked, failed = [], [], []
    for s in n.iter_all():
        if getattr(s, "is_deleted", False):
            continue
        folder = safe(getattr(s, "folder_name", None), "Note")
        title = safe(getattr(s, "title", None))
        entry = {"id": s.id, "title": getattr(s, "title", None), "folder": folder,
                 "modified": str(getattr(s, "modified_at", getattr(s, "modification_date", "")) or "")}
        if getattr(s, "is_locked", False):
            locked.append(entry)
            continue
        try:
            fdir = os.path.join(stage, folder)
            os.makedirs(fdir, exist_ok=True)
            p = n.export_note(s.id, fdir, export_mode="archival", assets_dir=os.path.join(fdir, "_allegati"))
            want = os.path.join(fdir, title + ".html")
            if os.path.abspath(p) != os.path.abspath(want):
                if os.path.exists(want):
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
    return {"note": len(index), "protette": len(locked), "errori": len(failed)}


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


def export_reminders(api, dest):
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
        write_atomic(os.path.join(out, name + ".json"), json.dumps({"lista": title, "id": l.id, "promemoria": rows},
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
    return {"liste": len(lists), "promemoria": total}


def run_once():
    from pyicloud import PyiCloudService
    started = time.time()
    status = {"started": started, "ok": False}
    work = None
    try:
        user = username()
        work = session_copy(user)
        api = PyiCloudService(user, password=None, cookie_directory=work)
        if api.requires_2fa or getattr(api, "requires_2sa", False):
            raise RuntimeError("la sessione Apple chiede un nuovo 2FA: rinnovala da iCloud Dashboard (#nome auth)")
        os.makedirs(DEST, exist_ok=True)
        status["note"] = export_notes(api, DEST)
        log(f"note esportate: {status['note']}")
        status["promemoria"] = export_reminders(api, DEST)
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
        try:
            write_atomic(STATUS, json.dumps(status, ensure_ascii=False, indent=1))
        except Exception:
            pass
    return status["ok"]


def main():
    os.umask(0)   # come «New Permissions» di Unraid: cartelle 777 e file 666, leggibili dalle share SMB
    if os.environ.get("PIM_ONCE") == "1":
        sys.exit(0 if run_once() else 1)
    time.sleep(int(os.environ.get("PIM_START_DELAY", "120")))   # lascia partire prima iclouddr
    while True:
        run_once()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
