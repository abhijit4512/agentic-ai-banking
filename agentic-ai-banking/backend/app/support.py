import re
from datetime import datetime
from .models import Transaction, Loan, Dispute, Customer, row, now as utcnow
POLICIES = [("Wire transfer fee", "Domestic wire transfers cost 15.00 USD; international wires cost 35.00 USD plus any intermediary fees."),
            ("KYC documents", "Individuals need a government photo ID, proof of address (under 3 months old) and proof of income or source of funds."),
            ("Dispute process", "Report disputed card transactions within 60 days. A provisional review starts after a dispute draft is confirmed."),
            ("Overdraft fee", "Overdraft fee is 25.00 USD per item, capped at 3 items per day.")]
SENSITIVE = re.compile(r"password|\bpin\b|cvv|\botp\b|one[- ]time|passcode", re.I)

def chat(db, cid, msg):
    """Narrow, read-only tools scoped to the caller's customer_id (enforced here, never by the LLM)."""
    m = msg.lower()
    if SENSITIVE.search(m):
        return {"answer": "For your security, never share passwords, PINs, CVVs or one-time codes in chat - the bank will never ask for them. I can help with transactions, disputes, loans and policies instead.", "sources": []}
    if cid is None: return {"answer": "No customer profile is linked to this user.", "sources": []}
    mt = re.search(r"TXN-\d{6}", msg, re.I)
    if "dispute" in m and mt:
        t = db.get(Transaction, mt.group(0).upper())
        if not t or t.customer_id != cid: return {"answer": "I can't find that transaction on your accounts.", "sources": []}
        d = Dispute(customer_id=cid, txn_id=t.id, reason=msg[:500]); db.add(d); db.commit()
        return {"answer": f"I created a DRAFT dispute #{d.id} for {t.id} ({float(t.amount):,.2f} {t.currency}, {t.merchant}). It is not submitted until reviewed by the bank's dispute team.", "sources": ["create_dispute_draft"]}
    if "flag" in m or "why" in m and "transaction" in m:
        ts = db.query(Transaction).filter_by(customer_id=cid, status="flagged").order_by(Transaction.ts.desc()).limit(5).all()
        if not ts: return {"answer": "None of your recent transactions are flagged.", "sources": ["get_transaction_history"]}
        return {"answer": "These transactions were flagged for review (flags are precautionary, not accusations):\n" + "\n".join(f"- {t.id}: {'; '.join(r['message'] for r in t.reasons)}" for t in ts), "sources": ["get_transaction_history"]}
    if "transaction" in m or "month" in m or "spend" in m:
        first = utcnow().replace(day=1, hour=0, minute=0, second=0)
        ts = db.query(Transaction).filter(Transaction.customer_id == cid, Transaction.ts >= first).order_by(Transaction.ts.desc()).all()
        if not ts: return {"answer": "No transactions found this month.", "sources": ["get_transaction_history"]}
        tot = sum(float(t.amount) for t in ts if t.status != "failed")
        return {"answer": f"You have {len(ts)} transactions this month totalling {tot:,.2f} (failed attempts excluded). Latest 8 shown.", "sources": ["get_transaction_history"],
                "blocks": [{"type": "table", "doc": "Transaction history", "page": "-", "rows": [["ID", "Date", "Merchant", "Amount", "Status"]] + [[t.id, f"{t.ts:%Y-%m-%d}", t.merchant, f"{float(t.amount):,.2f}", t.status] for t in ts[:8]], "uncertain": []}]}
    if "loan" in m:
        ls = db.query(Loan).filter_by(customer_id=cid).all()
        return {"answer": "\n".join(f"Loan #{l.id} ({l.loan_type}, {float(l.amount):,.0f}): status {l.status}" for l in ls) or "No loan applications found.", "sources": ["get_loan_application_status"]}
    hits = [p for p in POLICIES if any(w in m for w in re.findall(r"[a-z]{4,}", p[0].lower() + " " + p[1].lower()) if w in m.split() or w in m)]
    if hits: return {"answer": "\n".join(f"{t}: {x}" for t, x in hits[:2]), "sources": [f"Policy: {t}" for t, _ in hits[:2]]}
    return {"answer": "I don't have that information. I can help with transactions, flagged items, disputes (give a TXN reference), loan status and fee/KYC policies - or I can escalate to a human agent.", "sources": [], "escalate": True}
