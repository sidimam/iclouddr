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
