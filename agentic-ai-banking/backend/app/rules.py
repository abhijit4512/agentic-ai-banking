"""Transparent, configurable fraud rules. Deterministic: no ML, no LLM. Money uses Decimal."""
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import func
from .models import Transaction, Alert, now

D = lambda x: Decimal(str(x))
R = {"amount_threshold": Decimal("10000"), "velocity_count": 5, "velocity_minutes": 10, "failed_count": 3,
     "spike_multiplier": 5, "struct_low": Decimal("9000"), "struct_high": Decimal("9999.99"), "struct_count": 3, "flag_score": 40}


def evaluate(db, t):
    reasons = []
    def add(code, msg, pts): reasons.append({"code": code, "message": msg, "points": pts})
    amt = D(t.amount)
    if amt >= R["amount_threshold"]:
        add("HIGH_AMOUNT", f"Amount {amt:,.2f} is at/above threshold {R['amount_threshold']:,}", 35)
    prior = db.query(Transaction).filter(Transaction.account == t.account, Transaction.id != t.id, Transaction.ts <= t.ts)
    n = prior.filter(Transaction.ts >= t.ts - timedelta(minutes=R["velocity_minutes"])).count() + 1
    if n >= R["velocity_count"]:
        add("VELOCITY", f"{n} transactions within {R['velocity_minutes']} minutes", 25)
    fails = prior.filter(Transaction.status == "failed", Transaction.ts >= t.ts - timedelta(minutes=30)).count() + (t.status == "failed")
    if fails >= R["failed_count"]:
        add("REPEATED_FAILURES", f"{fails} failed attempts within 30 minutes", 25)
    hist = [D(x.amount) for x in prior.filter(Transaction.status != "failed").order_by(Transaction.ts.desc()).limit(30)]
    if len(hist) >= 5:
        avg = sum(hist, Decimal(0)) / len(hist)
        if amt > R["spike_multiplier"] * avg:
            add("AMOUNT_SPIKE", f"Amount is >{R['spike_multiplier']}x the account's recent average ({avg:,.2f})", 25)
    if R["struct_low"] <= amt <= R["struct_high"]:
        k = prior.filter(Transaction.ts >= t.ts - timedelta(days=3), Transaction.amount >= R["struct_low"], Transaction.amount <= R["struct_high"]).count() + 1
        if k >= R["struct_count"]:
            add("STRUCTURING_PATTERN", f"{k} transactions just under the reporting-style threshold in 3 days (indicator only)", 30)
    seen = {c for (c,) in prior.with_entities(Transaction.country).distinct() if c}
    if t.country and len(seen) >= 1 and t.country not in seen:
        add("NEW_GEOGRAPHY", f"First transaction from {t.country} on this account", 15)
    score = min(100, sum(r["points"] for r in reasons))
    sev = "critical" if score >= 80 else "high" if score >= 60 else "medium" if score >= R["flag_score"] else "low" if score > 0 else "none"
    return score, sev, reasons


def next_txn_id(db):
    """Next TXN-nnnnnn id based on the highest existing id (count()+1 breaks after any deletion).
    The primary key still guarantees uniqueness; use a DB sequence when moving to Postgres at scale."""
    last = db.query(func.max(Transaction.id)).scalar()
    return f"TXN-{(int(last.split('-')[1]) + 1) if last else 1:06d}"


def ingest_txn(db, ts=None, **kw):
    t = Transaction(id=next_txn_id(db), ts=ts or now(), **kw)
    db.add(t); db.flush()
    t.score, t.severity, t.reasons = evaluate(db, t)
    if t.score >= R["flag_score"]:
        t.status = "flagged" if t.status != "failed" else "failed"
        db.add(Alert(txn_id=t.id, customer_id=t.customer_id, severity=t.severity, score=t.score, reasons=t.reasons))
    db.flush()
    return t
