# iclouddr di casa: mandarons/icloud-drive (Drive e Foto, invariato) + modulo PIM (note e promemoria; poi posta, calendario,
# contatti). Il programma originale si avvia come sempre; il PIM gira accanto come processo separato e, se si guasta,
# Drive e Foto continuano. Versione di partenza fissata per digest: gli aggiornamenti si provano prima (vedi README).
ARG BASE=mandarons/icloud-drive:2.3.0@sha256:a352dd8a9e5b371d1f1f1c8fce886a2b88836204d0d857a2cd4474f505a60763
FROM ${BASE}
LABEL org.opencontainers.image.source="https://github.com/sidimam/iclouddr" \
      org.opencontainers.image.description="mandarons/icloud-drive + modulo PIM (note, promemoria) per Unraid"
# Ambiente Python separato da quello di iclouddr: un aggiornamento dell'uno non rompe le librerie dell'altro.
RUN apk add --no-cache isync \
 && python3 -m venv /opt/pim/venv \
 && /opt/pim/venv/bin/pip install --no-cache-dir pyicloud==2026.10.1 vdirsyncer==0.19.3 \
 && /opt/pim/venv/bin/python -c "import pyicloud.services.notes, pyicloud.services.reminders" \
 && mbsync --version && /opt/pim/venv/bin/vdirsyncer --version
COPY pim/ /opt/pim/
COPY pim-entrypoint.sh /usr/local/bin/pim-entrypoint.sh
RUN chmod 755 /usr/local/bin/pim-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/pim-entrypoint.sh"]
CMD ["/usr/local/bin/docker-entrypoint.sh"]
