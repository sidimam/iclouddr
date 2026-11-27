"""Account di posta, calendario e contatti di una persona (iCloud, Gmail, Outlook, altro IMAP), in sola lettura.

Gli account stanno in /config/pim-accounts.json (permessi 600), scritto da iCloud Control:
  {"accounts": [{"id": "icloud", "type": "icloud", "label": "iCloud", "email": "…", "password": "<password per app>",
                 "mail": true, "calendar": true, "contacts": true, "ics": ["https://…"], "exclude": ["Junk"]}]}
Ogni account scrive in <persona>/<label>/: Posta/ (Maildir, niente viene mai cancellato), Calendario/ (un .ics per evento,
una cartella per calendario), Contatti/ (un .vcf per contatto). Le password vanno solo in file temporanei 600 in /tmp.

- Posta: mbsync (isync) in sola lettura: Sync Pull, Remove None, Expunge None. Per Gmail solo «Tutti i messaggi» (la
  cartella con il flag \\All, trovata via IMAP): contiene tutto una volta sola, le etichette non si copiano.
- Calendario e contatti: vdirsyncer, server in sola lettura (read_only), «a wins»: segue il server.
- Calendari con link ICS (Gmail «indirizzo segreto in formato iCal», Outlook «pubblica calendario»): scaricati così come sono.
"""
import imaplib, json, os, re, shutil, subprocess, tempfile, urllib.request

ACCOUNTS = os.environ.get("PIM_ACCOUNTS", "/config/pim-accounts.json")
STATE = os.environ.get("PIM_STATE", "/config/pim-state")
VDIR = "/opt/pim/venv/bin/vdirsyncer"

PRESETS = {
    "icloud": {"imap": ("imap.mail.me.com", 993), "caldav": "https://caldav.icloud.com/", "carddav": "https://contacts.icloud.com/"},
    # Contatti Gmail: CardDAV di Google con la password per app (provato il 23/11/2026: 207 e 3.672 contatti);
    # {email} viene sostituito con l'indirizzo dell'account.
    "gmail": {"imap": ("imap.gmail.com", 993), "carddav": "https://www.googleapis.com/carddav/v1/principals/{email}/lists/"},
    "outlook": {"imap": ("outlook.office365.com", 993)},   # Outlook.com dal 2024 vuole OAuth: senza, l'accesso viene rifiutato
}


def load():
    try:
        return json.load(open(ACCOUNTS)).get("accounts", [])
    except (FileNotFoundError, ValueError):
        return []


def _secret_file(text, tmp):
    p = os.path.join(tmp, "pw")
    with open(p, "w") as f:
        f.write(text)
    os.chmod(p, 0o600)
    return p


def _run(cmd, timeout, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _mutf7(s):
    """Nome di cartella IMAP in UTF-7 modificato (RFC 3501 §5.1.3) → testo normale (es. «Ricevute &AOg-» → «Ricevute è»)."""
    import base64
    out, i = [], 0
    while i < len(s):
        if s[i] == "&":
            j = s.index("-", i)
            if j == i + 1:
                out.append("&")
            else:
                b = s[i + 1:j].replace(",", "/")
                out.append(base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-16-be"))
            i = j + 1
        else:
            out.append(s[i]); i += 1
    return "".join(out)


def _imap_folders(host, port, user, pw):
    """Cartelle che il server ha ADESSO, con «/» come separatore (come le vede mbsync). None se l'elenco non riesce.
    0.2.13: mbsync con Patterns * prende anche le cartelle che esistono solo nella copia locale; se una cartella viene
    spostata o cancellata su iCloud (Simone, 24/11/2026: «Viaggi/2027/Non confermato» spostata sotto «Malesia»), con
    Remove None mbsync si ferma con «far side box … cannot be opened anymore» a ogni giro e la posta non si aggiorna più.
    Con l'elenco esplicito delle cartelle del server la vecchia copia locale resta com'è (archivio) e il giro continua."""
    m = imaplib.IMAP4_SSL(host, port, timeout=60)
    try:
        m.login(user, pw)
        typ, data = m.list()
        if typ != "OK":
            return None
        out, i = [], 0
        while i < len(data or []):
            raw = data[i]
            if isinstance(raw, tuple):   # nome come letterale IMAP: (intestazione, nome)
                head, name = raw[0].decode("utf-8", "replace"), raw[1].decode("utf-8", "replace")
            elif raw is None:
                i += 1; continue
            else:
                head = raw.decode("utf-8", "replace"); name = None
            mm = re.match(r'\((?P<f>[^)]*)\)\s+(?P<d>"(?:[^"\\]|\\.)*"|NIL)\s*(?P<n>.*)$', head)
            if not mm:
                i += 1; continue
            if name is None:
                n = mm.group("n").strip()
                name = re.sub(r'\\(.)', r'\1', n[1:-1]) if n.startswith('"') and n.endswith('"') else n
            delim = mm.group("d").strip('"').replace("\\\\", "\\") if mm.group("d") != "NIL" else ""
            name = _mutf7(name)
            if delim and delim != "/":
                name = name.replace(delim, "/")
            out.append(name)
            i += 1
        return out or None
    except Exception:
        return None
    finally:
        try:
            m.logout()
        except Exception:
            pass


def _gmail_all_mail(host, port, user, pw):
    """Nome (localizzato) della cartella Gmail con il flag \\All, es. «[Gmail]/Tutti i messaggi»."""
    m = imaplib.IMAP4_SSL(host, port, timeout=60)
    try:
        m.login(user, pw)
        typ, data = m.list()
        for raw in data or []:
            line = raw.decode("utf-8", "replace")
            if "\\All" in line:
                return re.search(r'"([^"]+)"\s*$', line).group(1) if re.search(r'"([^"]+)"\s*$', line) else line.rsplit(" ", 1)[-1]
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return None


def sync_mail(acc, base, log):
    host, port = (acc.get("imap_host"), int(acc.get("imap_port") or 993)) if acc.get("imap_host") else PRESETS.get(acc["type"], {}).get("imap", (None, 993))
    if not host:
        raise RuntimeError("server IMAP mancante")
    dest = os.path.join(base, "Posta")
    os.makedirs(dest, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pim-mail-")
    try:
        pw = _secret_file(acc["password"], tmp)
        patterns = "*"
        if acc["type"] == "gmail":
            allm = _gmail_all_mail(host, port, acc["email"], acc["password"])
            if not allm:
                raise RuntimeError("cartella «Tutti i messaggi» di Gmail non trovata (IMAP attivo?)")
            patterns = f'"{allm}"'
        else:
            far = _imap_folders(host, port, acc["email"], acc["password"])
            if far:   # solo le cartelle che il server ha adesso (0.2.13); se l'elenco non riesce resta «*»
                # una riga «Patterns» per cartella: mbsync legge righe di lunghezza limitata (102 cartelle su una riga
                # spezzavano la configurazione) e somma le righe Patterns nell'ordine in cui le trova
                patterns = "\nPatterns ".join('"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"' for x in far)
        excl = "".join(f'Patterns !"{x}"\n' for x in acc.get("exclude", []) if x)   # esclusioni dopo: vince l'ultima riga che corrisponde
        state = os.path.join(STATE, acc["id"], "mbsync")
        os.makedirs(state, exist_ok=True)
        cfg = os.path.join(tmp, "mbsyncrc")
        with open(cfg, "w") as f:
            f.write(f"""IMAPAccount a
Host {host}
Port {port}
User "{acc["email"]}"
PassCmd "cat '{pw}'"
TLSType IMAPS
Timeout 180
PipelineDepth 8

IMAPStore remote
Account a

MaildirStore local
Path "{dest}/"
Inbox "{dest}/INBOX"
SubFolders Verbatim

Channel c
Far :remote:
Near :local:
Patterns {patterns}
{excl}Create Near
Remove None
Expunge None
Sync Pull
SyncState "{state}/"
CopyArrivalDate yes
""")
        os.chmod(cfg, 0o600)
        rc, out = _run(["mbsync", "-c", cfg, "-a"], timeout=6 * 3600)
        if rc != 0:
            raise RuntimeError("mbsync: " + " ".join(out.strip().splitlines()[-3:])[:300])
        n = sum(len(fs) for _, _, fs in os.walk(dest) if fs) if os.path.isdir(dest) else 0
        return {"messaggi": n}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _vdir(acc, kind, url, dest, ext):
    tmp = tempfile.mkdtemp(prefix=f"pim-{kind}-")
    try:
        pw = _secret_file(acc["password"], tmp)
        st = os.path.join(STATE, acc["id"], "vdir-" + kind)
        os.makedirs(st, exist_ok=True)
        os.makedirs(dest, exist_ok=True)
        typ = "caldav" if kind == "cal" else "carddav"
        cfg = os.path.join(tmp, "config")
        with open(cfg, "w") as f:
            f.write(f"""[general]
status_path = "{st}/"

[pair p]
a = "remote"
b = "local"
collections = ["from a"]
conflict_resolution = "a wins"
metadata = ["displayname"]

[storage remote]
type = "{typ}"
url = "{url}"
username = "{acc["email"]}"
password.fetch = ["command", "cat", "{pw}"]
read_only = true

[storage local]
type = "filesystem"
path = "{dest}/"
fileext = "{ext}"
""")
        env = {**os.environ, "HOME": tmp}
        rc, out = _run(["sh", "-c", f'yes | {VDIR} -c "{cfg}" discover && {VDIR} -c "{cfg}" metasync; {VDIR} -c "{cfg}" sync'], timeout=3600, env=env)
        if rc != 0:
            raise RuntimeError(f"vdirsyncer {kind}: " + " ".join(out.strip().splitlines()[-3:])[:300])
        n = sum(1 for _, _, fs in os.walk(dest) for x in fs if x.endswith(ext))
        return n
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sync_calendar(acc, base):
    dest = os.path.join(base, "Calendario")
    res = {}
    url = acc.get("caldav") or PRESETS.get(acc["type"], {}).get("caldav")
    if url and acc.get("password"):
        res["eventi"] = _vdir(acc, "cal", url, dest, ".ics")
    links = [u for u in acc.get("ics", []) if u.strip()]
    if links:
        os.makedirs(os.path.join(dest, "Link ICS"), exist_ok=True)
        for i, u in enumerate(links, 1):
            req = urllib.request.Request(u.strip(), headers={"User-Agent": "iclouddr-pim"})
            data = urllib.request.urlopen(req, timeout=120).read()
            if b"BEGIN:VCALENDAR" not in data[:2000]:
                raise RuntimeError(f"il link ICS {i} non restituisce un calendario")
            name = re.search(rb"X-WR-CALNAME:([^\r\n]+)", data)
            fname = re.sub(r'[\\/:*?"<>|]', "_", name.group(1).decode("utf-8", "replace").strip() if name else f"Calendario {i}")[:80]
            with open(os.path.join(dest, "Link ICS", fname + ".ics"), "wb") as f:
                f.write(data)
        res["link_ics"] = len(links)
    return res


def sync_contacts(acc, base):
    url = acc.get("carddav") or PRESETS.get(acc["type"], {}).get("carddav")
    if not url:
        # Prima della 0.2.12 qui tornava {} e il giro risultava «ok» senza copiare nulla (account «in attesa» per sempre).
        raise RuntimeError(f"contatti non disponibili per gli account {acc['type']}: manca l'indirizzo CardDAV")
    if not acc.get("password"):
        raise RuntimeError("manca la password per app")
    return {"contatti": _vdir(acc, "card", url.format(email=acc["email"]), os.path.join(base, "Contatti"), ".vcf")}
