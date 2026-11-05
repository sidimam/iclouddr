"""Cosa è condiviso su iCloud (dalla 0.2.6), in sola lettura: note, liste di promemoria, elementi di iCloud Drive.

Apple lo dice nei metadati dei record CloudKit e nelle voci del Drive:
- note: il record della nota (o della sua cartella) ha `share` (un record Share-…);
- promemoria: il record della lista ha `share` (es. le liste Regali e Famiglia);
- Drive: la voce ha `shareID` e `share` (FROM_ME, o TO_ME se un altro la condivide con la persona); ogni cartella dice in `shareCount` quanti elementi condivisi ci sono
  sotto di lei, così si scende solo dove serve. Il contenuto di una cartella condivisa è condiviso con lei.
Il risultato va in pim-status.json («condivisi»), che iCloud Dashboard legge per scrivere in blu questi elementi.
Le liste e le note che altri condividono con la persona invece stanno nel database condiviso di CloudKit e qui non compaiono.
"""
from pyicloud.common.cloudkit import CKRecord, CKZoneChangesZoneReq


def _records(raw, zone, rtype):
    for z in raw.changes(zone_req=CKZoneChangesZoneReq(zoneID=zone, desiredRecordTypes=[rtype], desiredKeys=["Deleted"], reverse=False)):
        for rec in z.records:
            if isinstance(rec, CKRecord) and rec.recordType == rtype:
                yield rec


def notes(api):
    """Identificativi delle note condivise: la nota stessa o la cartella che la contiene."""
    from pyicloud.services.notes._constants import NOTES_ZONE
    n = api.notes
    folders = {r.recordName for r in _records(n._raw, NOTES_ZONE, "Folder") if getattr(r, "share", None)}
    ids = {r.recordName for r in _records(n._raw, NOTES_ZONE, "Note") if getattr(r, "share", None)}
    return ids, folders


def lists(api):
    """Identificativi delle liste di promemoria condivise."""
    reads = api.reminders._reads
    out = set()
    for zone in reads._iter_zone_change_pages(desired_record_types=["List"]):
        for rec in zone.records:
            if isinstance(rec, CKRecord) and rec.recordType == "List" and getattr(rec, "share", None):
                out.add(rec.recordName)
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def drive(api, limit=2000):
    """Percorsi (relativi alla radice di iCloud Drive) degli elementi condivisi, con chi condivide."""
    out = []

    def walk(node, path):
        for name in node.dir() or []:
            if len(out) >= limit:
                return
            item = node[name]
            d = item.data
            rel = f"{path}/{name}" if path else name
            if d.get("shareID") or d.get("share"):
                out.append({"path": rel, "share": d.get("share") or "", "folder": d.get("type") == "FOLDER"})
            elif d.get("type") in ("FOLDER", "APP_LIBRARY") and _int(d.get("shareCount")) > 0:
                walk(item, rel)

    walk(api.drive.root, "")
    return out
