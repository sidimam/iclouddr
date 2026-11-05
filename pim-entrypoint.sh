#!/bin/sh
# Avvia il modulo PIM in background (come l'utente abc dell'immagine originale, con un riavvio se termina) e poi passa
# il controllo, invariato, all'avvio originale di iclouddr. PIM_ENABLED=0 lo spegne del tutto.
if [ "${PIM_ENABLED:-1}" != "0" ]; then
  (
    sleep 5   # l'avvio originale sistema UID/GID di abc
    mkdir -p "${PIM_DEST:-/icloud/pim}" && chown abc:users "${PIM_DEST:-/icloud/pim}" 2>/dev/null
    while true; do
      su-exec abc /opt/pim/venv/bin/python /opt/pim/pim.py
      echo "$(date '+%Y-%m-%d %H:%M:%S') :: PIM :: il modulo PIM è terminato, riparte tra 60 s"
      sleep 60
    done
  ) &
fi
exec "$@"
