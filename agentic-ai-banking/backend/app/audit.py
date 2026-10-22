"""Append-only, hash-chained audit log. Editing or deleting a row breaks verification."""
import hashlib
from sqlalchemy import event
from .models import AuditLog, now

GENESIS = "0" * 64


def _digest(prev, ts, actor, action, detail):
    raw = "|".join([prev, ts.isoformat(), actor or "", action or "", detail or ""])
    return hashlib.sha256(raw.encode()).hexdigest()


def add_entry(db, actor, action, detail=""):
    """Add (not commit) a chained audit row. Call inside the caller's transaction."""
    last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    prev = (last.hash if last and last.hash else GENESIS)
    ts = now()
    entry = AuditLog(ts=ts, actor=actor, action=action, detail=str(detail)[:500], prev_hash=prev)
    entry.hash = _digest(prev, ts, entry.actor, entry.action, entry.detail)
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db):
    """Walk the chain in order. Returns {ok, checked, first_bad_id}."""
    prev, checked = GENESIS, 0
    for e in db.query(AuditLog).order_by(AuditLog.id.asc()):
        if e.hash is None:  # rows written before the chain existed are skipped, not trusted
            continue
        if e.prev_hash != prev or e.hash != _digest(e.prev_hash, e.ts, e.actor, e.action, e.detail):
            return {"ok": False, "checked": checked, "first_bad_id": e.id}
        prev, checked = e.hash, checked + 1
    return {"ok": True, "checked": checked, "first_bad_id": None}


@event.listens_for(AuditLog, "before_update")
def _no_update(mapper, connection, target):
    raise RuntimeError("audit_logs is append-only")


@event.listens_for(AuditLog, "before_delete")
def _no_delete(mapper, connection, target):
    raise RuntimeError("audit_logs is append-only")
