# Registro delle modifiche — iclouddr

Una voce per ogni modifica, la più recente in alto, raggruppate per giorno. Serve a ricostruire lo stato del progetto
senza rileggere le conversazioni: ogni commit aggiunge qui la sua voce (cosa, perché, dove, come è stato provato).
Le voci fino al 16/11/2026 sono ricostruite dalla storia git (messaggio del commit e hash).

## 2026-11-16
- Nuovo `changelog.md`: storia ricostruita dai commit (strumento `tools/changelog_da_git.sh` della cartella Claude); da qui in poi ogni commit aggiunge la sua voce in cima.

## 2026-11-12
- 0.2.11: all'avvio /icloud passa a PUID:PGID senza ricorsione, così l'avvio originale non fa chown -R su foto e documenti (Immich rimetteva tutto in coda) (`8539d37`)
- 0.2.10: note, promemoria e contatti una volta al giorno (PIM_INTERVAL e il nuovo PIM_CONTACTS_INTERVAL a 86400), calendari sempre ogni ora (`4d357e5`)
- iCloud Dashboard ora si chiama iCloud Control: README e commenti (`b84b160`)

## 2026-11-11
- README: link alla wiki (`2e401a2`)

## 2026-11-09
- 0.2.9: a fine giro scrive l'elenco dei file e delle foto presenti su iCloud (/config/elenco-icloud-*.json.gz) per l'icona di iCloud Dashboard (`27cc2ee`)

## 2026-11-08
- make_config: ignora Documents/Claude (cartella di lavoro del Mac sincronizzata con iCloud); stackdump.py per campionare il giro con sys.remote_exec (`e22deb8`)

## 2026-11-06
- 0.2.8: scadenza complessiva (ICLOUDDR_HTTP_DEADLINE, 300 s) per l'intestazione delle risposte: le risposte a goccia di Apple non bloccano più il giro di iCloud Drive (`7b8df12`)
- 0.2.7: le esportazioni delle note lasciate a metà da un riavvio (pim-note-…) si cancellano al giro dopo (`30f9052`)

## 2026-11-05
- Documentazione: il Drive segnala anche le cartelle condivise con la persona (TO_ME) (`3a375bf`)
- PIM 0.2.6: elenco degli elementi condivisi (note, liste di promemoria, iCloud Drive) in pim-status.json (`f8f7a99`)
- 0.2.5: attesa massima predefinita su tutte le richieste HTTP di iclouddr (connessioni appese durante l'elenco del Drive); configurazione unica in unraid/make_config.py (`fca9ac3`)
- 0.2.4: stato «in corso» degli account durante il giro (via l'errore vecchio) (`7401cd9`)
- 0.2.3: cartella dell'account = nome del servizio (iCloud, Gmail, Outlook) o quella scelta dalla dashboard (`99e6420`)
- 0.2.2: percorsi tra virgolette nella configurazione di mbsync (etichette con spazi) (`eb8f413`)
- 0.2.1: note con lo stesso titolo nella stessa cartella non si sovrascrivono più (`621d6c7`)
- 0.2.0: account di posta, calendario e contatti (iCloud, Gmail, Outlook, IMAP) con mbsync e vdirsyncer, link ICS, pulsante Sincronizza ora (`ab8cafb`)
- 0.1.1: permessi di Unraid (777/666) sulle cartelle esportate (`084b2e7`)
- PIM: date dei promemoria in formato italiano; dettagli solo per i promemoria da fare (`340f6a4`)
- iclouddr: mandarons/icloud-drive 2.3.0 + modulo PIM (note e promemoria via pyicloud, sola lettura) (`20db130`)
