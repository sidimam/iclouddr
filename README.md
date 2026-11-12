# iclouddr

Immagine per i container iCloud di casa su Unraid: **[mandarons/icloud-drive](https://github.com/mandarons/icloud-docker)**
(iCloud Drive e Foto, invariato) più un **modulo PIM** che copia sul NAS le **note** e i **promemoria** di iCloud. Posta,
calendario e contatti arriveranno nello stesso modulo, con una password per app.

Tutto in sola lettura: niente viene mai scritto verso Apple. Il progetto completo sta in RepoCasa,
`docs/progetti/icloud-completo.html`; i container li gestisce [iCloud Control](https://github.com/sidimam/icloud-control).

Documentazione completa nella **[wiki](https://github.com/sidimam/iclouddr/wiki)**: architettura, installazione su Unraid,
configurazione, dati prodotti, account collegati, aggiornamenti, risoluzione dei problemi e changelog.

## Come funziona

- L'immagine parte da una versione **fissata per digest** di `mandarons/icloud-drive` (oggi 2.3.0) e ne lascia intatti codice
  e avvio: `pim-entrypoint.sh` lancia il modulo PIM in background e poi passa il controllo, invariato, all'avvio originale.
- Il PIM ha un **ambiente Python suo** (`/opt/pim/venv`, `pyicloud==2026.10.1`), separato da quello di iclouddr.
- Il PIM è un **processo separato**: se termina viene riavviato dopo 60 s, e Drive e Foto continuano comunque.
- **Sessione Apple**: la stessa di iclouddr. A ogni giro il PIM ne fa una copia in `/tmp` (aggiungendo il file `….cookiejar`
  che si aspetta pyicloud) e lavora su quella, così non riscrive mai `/config/session_data`. Nessun secondo 2FA: quando la
  sessione scade, si rinnova come sempre da iCloud Control (`#nome auth`).

## Cosa produce

Nella cartella montata su `/icloud/pim` (per Simone `/mnt/user/documents/Simone/iCloud`):

| Percorso | Contenuto |
|---|---|
| `Note/<cartella>/<titolo>.html` | Ogni nota come pagina HTML, con immagini e allegati in `_allegati/` accanto |
| `Note/indice.json` | Elenco delle note, di quelle protette da password (non leggibili) e degli errori |
| `Promemoria/<lista>.json` | Tutti i campi di ogni promemoria, con avvisi, tag e ripetizioni |
| `Promemoria/<lista>.md` | La stessa lista da leggere, con caselle e scadenze |

**Elementi condivisi** (dalla 0.2.6): a ogni giro il PIM chiede ad Apple cosa è condiviso con altri e lo scrive in
`/config/pim-status.json` (`condivisi`): note (la nota o la sua cartella ha un record `Share`), liste di promemoria (idem) e
voci di iCloud Drive (`shareID`/`share: FROM_ME`; si scende solo nelle cartelle con `shareCount` > 0, quindi costa pochi
secondi). Nell'indice delle note la voce ha `"shared": true`, nel JSON della lista `"condivisa": true`. iCloud Control
li scrive in blu. Sul Drive compaiono anche le cartelle condivise *con* la persona (`share: TO_ME`); le note e le liste
condivise da altri stanno nel database condiviso di CloudKit e qui non compaiono.

La cartella `Note` viene sostituita intera solo a giro riuscito (dalla 0.2.7 le copie `pim-note-…` lasciate a metà da un riavvio
del container si cancellano al giro dopo); le liste di promemoria cancellate su iCloud spariscono anche qui.
Le versioni vecchie restano nella copia sul disco USB Elements, che non cancella mai niente. Lo stato dell'ultimo giro è in
`/config/pim-status.json`.

## Attese massime sulle richieste (0.2.5 e 0.2.8)

`sitecustomize.py` (in `/usr/local/lib/python3.14/site-packages`) mette due limiti alle richieste HTTP di iclouddr, senza
toccarne il codice: un timeout predefinito per connessione e singola lettura (`ICLOUDDR_HTTP_TIMEOUT`, `30,120`) e, dalla 0.2.8,
una **scadenza complessiva per l'intestazione della risposta** (`ICLOUDDR_HTTP_DEADLINE`, 300 s): se Apple manda dati a goccia
(~1 KB/s) il timeout di lettura non scatta mai e il giro di iCloud Drive restava appeso per ore (Sofia, 6/11/2026, visto con
uno stack dump: `get_node_data` → `ssl.read`). Allo scadere la connessione viene chiusa, la richiesta fallisce e iclouddr riprova.
Lo scaricamento del contenuto dei file non ha scadenza.

## Elenco di cosa c'è su iCloud (0.2.9)

Con `remove_obsolete: false` i file cancellati da iCloud restano sul NAS, e guardando la cartella non si capisce più cosa è
ancora su iCloud. A fine giro mandarons sa già quali file locali corrispondono a elementi presenti su iCloud: `sync_drive`
li restituisce, `sync_photos` li raccoglie nel set che passa a `_sync_albums_by_configuration`. `sitecustomize.py` avvolge
queste funzioni quando i moduli vengono importati (il codice di mandarons non cambia) e scrive l'elenco, con i percorsi del
container, in `/config/elenco-icloud-drive.json.gz` e `/config/elenco-icloud-foto.json.gz` (`{"kind", "when", "files"}`).
iCloud Control ≥ 3.21 lo usa per l'icona «su iCloud / solo sul NAS». Se una libreria di foto non si è potuta leggere,
l'elenco delle foto non viene aggiornato perché sarebbe incompleto. Le cartelle in `ignore` non compaiono nell'elenco.

## Avvio senza chown dei mount (0.2.11)

L'avvio originale fa `chown -R abc:abc /icloud` quando la cartella `/icloud` del container non è di abc, cioè ogni volta
che il container viene ricreato. Il chown scendeva in tutti i mount (foto, documenti, posta) e cambiava il ctime di ogni
file: il watcher di Immich li rimetteva in coda tutti come nuovi (il 12/11/2026 130.000 lavori falliti con «duplicate key»).
Dalla 0.2.11 `pim-entrypoint.sh` assegna prima solo la cartella `/icloud` a `PUID:PGID`, non ricorsivo.

## Variabili

| Variabile | Default | Effetto |
|---|---|---|
| `PIM_ENABLED` | `1` | `0` spegne il modulo: resta l'iclouddr originale |
| `ICLOUDDR_ELENCO` | `1` | `0` non scrive l'elenco di cosa c'è su iCloud (0.2.9) |
| `ICLOUDDR_ELENCO_DIR` | `/config` | Dove scrivere l'elenco |
| `PIM_DEST` | `/icloud/pim` | Dove scrivere |
| `PIM_INTERVAL` | `86400` | Secondi fra un giro e l'altro di note e promemoria (24 ore dalla 0.2.10; prima 6 ore) |
| `PIM_MAIL_INTERVAL` | `900` | Posta degli account collegati (15 minuti) |
| `PIM_DAV_INTERVAL` | `3600` | Calendari (1 ora) |
| `PIM_CONTACTS_INTERVAL` | `86400` | Contatti (24 ore, separati dai calendari dalla 0.2.10) |
| `PIM_START_DELAY` | `120` | Attesa dopo l'avvio, per lasciare partire prima iclouddr |

## Aggiornamenti di mandarons/icloud-drive

Il workflow «Nuove versioni di iclouddr» controlla ogni lunedì Docker Hub. Se c'è una versione nuova, prova a costruire
l'immagine sopra di essa e apre una issue con l'esito; niente si aggiorna da solo. Per aggiornare: cambiare `BASE` nel
`Dockerfile`, pubblicare un tag `vX.Y.Z`, installarlo su `iclouddr-sdimambro`, controllare un giro di Drive, Foto e PIM nei
log, poi sugli altri container. Per tornare indietro basta rimettere il tag precedente: i dati non si toccano.

## Licenza

Il modulo PIM e gli script di questo repository sono BSD-3-Clause come l'immagine di partenza
(© 2021 Mandar Patil per mandarons/icloud-docker).
