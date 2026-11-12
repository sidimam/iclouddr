# iclouddr di casa: attesa massima predefinita per ogni richiesta HTTP di iclouddr (mandarons/icloud-drive, icloudpy).
# Senza, una connessione che Apple chiude a metà (CLOSE_WAIT) lascia il giro di iCloud Drive appeso per ore: succedeva
# a Sofia, con 8.571 cartelle da elencare. Con l'attesa massima la richiesta fallisce, iclouddr registra «Sync failed and
# will be retried» e riparte al giro successivo. Le richieste che indicano già un timeout (download dei file) non cambiano.
# ICLOUDDR_HTTP_TIMEOUT="connessione,lettura" in secondi (default 30,120); vuoto o "0" lo spegne.
import os

try:
    _t = os.environ.get("ICLOUDDR_HTTP_TIMEOUT", "30,120").strip()
    if _t and _t != "0":
        _parts = [float(x) for x in _t.split(",")]
        _default = (_parts[0], _parts[1] if len(_parts) > 1 else _parts[0])
        import requests.sessions as _rs

        _orig = _rs.Session.request

        def _request(self, method, url, **kwargs):
            if kwargs.get("timeout") is None:
                kwargs["timeout"] = _default
            return _orig(self, method, url, **kwargs)

        _rs.Session.request = _request
except Exception:   # non deve mai impedire l'avvio di iclouddr
    pass

# 0.2.8: scadenza COMPLESSIVA per la risposta. Il timeout di lettura vale per ogni singola recv: se Apple manda dati a goccia
# (~1 KB/s, visto a Sofia il 6/11/2026: 4+ minuti sulla stessa connessione, status line mai completa) non scatta mai.
# Se l'intestazione della risposta non arriva entro ICLOUDDR_HTTP_DEADLINE secondi (default 300) la connessione viene chiusa:
# la richiesta fallisce e iclouddr riprova. Vale solo per l'attesa dell'intestazione, non per lo scaricamento del contenuto.
try:
    _dl = float(os.environ.get("ICLOUDDR_HTTP_DEADLINE", "300") or 0)
    if _dl > 0:
        import socket as _socket, threading as _threading
        import urllib3.connection as _uc

        _orig_getresponse = _uc.HTTPConnection.getresponse

        def _getresponse(self, *args, **kwargs):
            sock = getattr(self, "sock", None)
            timer = None
            if sock is not None:
                def _cut():
                    try:
                        sock.shutdown(_socket.SHUT_RDWR)
                    except Exception:
                        pass
                timer = _threading.Timer(_dl, _cut)
                timer.daemon = True
                timer.start()
            try:
                return _orig_getresponse(self, *args, **kwargs)
            finally:
                if timer is not None:
                    timer.cancel()

        _uc.HTTPConnection.getresponse = _getresponse
except Exception:
    pass

# 0.2.9: elenco di cosa c'è su iCloud, per l'icona «su iCloud / solo sul NAS» di iCloud Control. A fine giro iclouddr sa già
# quali file locali corrispondono a elementi presenti su iCloud: sync_drive li restituisce, sync_photos li raccoglie nel set
# «files» che passa a _sync_albums_by_configuration. Qui si avvolgono le due funzioni quando il modulo viene importato (il
# codice di mandarons non cambia) e si scrive l'elenco in /config/elenco-icloud-{drive,foto}.json.gz. Con remove_obsolete
# spento i file cancellati da iCloud restano sul NAS: sono quelli che non compaiono nell'elenco. Se una libreria di foto
# non si è potuta leggere, l'elenco delle foto non viene aggiornato (sarebbe incompleto). ICLOUDDR_ELENCO=0 lo spegne.
try:
    if os.environ.get("ICLOUDDR_ELENCO", "1") != "0":
        import sys as _sys, importlib.abc as _iabc

        _ELENCO_DIR = os.environ.get("ICLOUDDR_ELENCO_DIR", "/config")

        def _dump(kind, files):
            import json, gzip, time
            p = os.path.join(_ELENCO_DIR, f"elenco-icloud-{kind}.json.gz")
            tmp = p + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump({"kind": kind, "when": time.time(), "files": sorted(str(x) for x in files)}, f, ensure_ascii=False)
            os.replace(tmp, p)

        def _wrap_drive(m):
            orig = m.sync_drive

            def sync_drive(*a, **kw):
                files = orig(*a, **kw)
                try:
                    if files is not None:
                        _dump("drive", files)
                except Exception:
                    pass
                return files

            m.sync_drive = sync_drive

        def _wrap_photos(m):
            orig_sp, orig_alb, cap = m.sync_photos, m._sync_albums_by_configuration, {}

            def albums(*a, **kw):
                cap["files"] = a[5] if len(a) > 5 else kw.get("files")
                cap["failed"] = kw.get("failed_libraries")
                return orig_alb(*a, **kw)

            def sync_photos(*a, **kw):
                cap.clear()
                r = orig_sp(*a, **kw)
                try:
                    if cap.get("files") is not None and not cap.get("failed"):
                        _dump("foto", cap["files"])
                except Exception:
                    pass
                return r

            m._sync_albums_by_configuration = albums
            m.sync_photos = sync_photos

        _WRAP = {"src.sync_drive": _wrap_drive, "src.sync_photos": _wrap_photos}

        class _ElencoFinder(_iabc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name not in _WRAP:
                    return None
                spec = None
                for f in _sys.meta_path:
                    if f is not self and hasattr(f, "find_spec"):
                        spec = f.find_spec(name, path, target)
                        if spec:
                            break
                if not spec or not spec.loader:
                    return None
                orig_exec = spec.loader.exec_module

                def exec_module(module, _o=orig_exec, _n=name):
                    _o(module)
                    try:
                        _WRAP[_n](module)
                    except Exception:
                        pass

                spec.loader.exec_module = exec_module
                return spec

        _sys.meta_path.insert(0, _ElencoFinder())
except Exception:
    pass
