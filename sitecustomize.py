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
