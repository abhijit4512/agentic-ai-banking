"""Deterministic loan maths (Decimal). The LLM never does this arithmetic."""
from decimal import Decimal, ROUND_HALF_UP
Q = Decimal("0.01")
POLICY = {"max_dti": Decimal("0.43"), "review_dti": Decimal("0.36"), "max_lti": Decimal("5"), "min_income": Decimal("1500")}
REQUIRED = ["income_proof", "bank_statement", "identity"]
D = lambda x: Decimal(str(x))

def pmt(principal, annual_rate_pct, n):
    p, r = D(principal), D(annual_rate_pct) / 100 / 12
    if n <= 0 or p <= 0: raise ValueError("amount and term must be positive")
    if r == 0: return (p / n).quantize(Q, ROUND_HALF_UP)
    f = (1 + r) ** n
    return (p * r * f / (f - 1)).quantize(Q, ROUND_HALF_UP)

def schedule(principal, annual_rate_pct, n):
    bal, r, pay, rows = D(principal), D(annual_rate_pct) / 100 / 12, pmt(principal, annual_rate_pct, n), []
    for i in range(1, n + 1):
        interest = (bal * r).quantize(Q, ROUND_HALF_UP)
        princ = bal if i == n else pay - interest
        bal = (bal - princ).quantize(Q)
        rows.append({"n": i, "payment": float(princ + interest), "interest": float(interest), "principal": float(princ), "balance": float(bal)})
    return rows

def assess(l):
    inc, debt, amt = D(l.income), D(l.debt), D(l.amount)
    emi = pmt(amt, l.rate, l.term_months)
    dti = ((debt + emi) / inc).quantize(Decimal("0.0001")) if inc > 0 else None
    lti = (amt / (inc * 12)).quantize(Decimal("0.01")) if inc > 0 else None
    checks = []
    def chk(name, val, limit, st): checks.append({"name": name, "value": str(val), "limit": str(limit), "status": st})
    chk("Minimum monthly income", inc, POLICY["min_income"], "pass" if inc >= POLICY["min_income"] else "fail")
    if dti is not None:
        chk("Debt-to-income (incl. new instalment)", dti, POLICY["max_dti"], "fail" if dti > POLICY["max_dti"] else "review" if dti > POLICY["review_dti"] else "pass")
        chk("Loan-to-annual-income", lti, POLICY["max_lti"], "pass" if lti <= POLICY["max_lti"] else "review")
    have = {d["doc_type"] for d in (l.docs or [])}
    missing = [x for x in REQUIRED if x not in have]
    if any(c["status"] == "fail" for c in checks): rec, status = "Recommend rejection (policy check failed)", "recommended_rejection"
    elif missing: rec, status = "Documents pending: " + ", ".join(missing), "documents_pending"
    elif any(c["status"] == "review" for c in checks): rec, status = "Needs underwriter review", "under_review"
    else: rec, status = "Recommend approval (all configured checks passed)", "recommended_approval"
    return {"monthly_instalment": float(emi), "dti": float(dti) if dti is not None else None, "lti": float(lti) if lti is not None else None,
            "checks": checks, "missing_documents": missing, "recommendation": rec, "suggested_status": status,
            "credit_bureau": "Not available - no authorized bureau integration configured (no score is fabricated)",
            "disclaimer": "Automated recommendation only. A human underwriter must make the final decision."}
