import re, difflib
# SYNTHETIC demo screening data. Replace with an authorized provider adapter in production.
LISTS = [{"name": "Ivan Petrovich Volkov", "list": "SYNTHETIC-SANCTIONS", "country": "RU"},
         {"name": "Maria Elena Duarte", "list": "SYNTHETIC-PEP", "country": "MX"},
         {"name": "Daniel C Okafor", "list": "SYNTHETIC-WATCHLIST", "country": "NG"},
         {"name": "Northwind Trading FZE", "list": "SYNTHETIC-ADVERSE-MEDIA", "country": "AE"}]

def _t(s): return " ".join(sorted(re.sub(r"[^a-z ]", " ", s.lower()).split()))

def screen(name, country=None, threshold=0.75):
    out = []
    for e in LISTS:
        r = difflib.SequenceMatcher(None, _t(name), _t(e["name"])).ratio()
        if r >= threshold:
            on = ["name"] + (["country"] if country and country.upper() == e["country"] else [])
            out.append({"matched_name": e["name"], "list": e["list"], "confidence": round(r, 2), "matched_on": on, "source": "synthetic demo dataset"})
    return sorted(out, key=lambda x: -x["confidence"])

def sar_draft(case, cust, txns):
    lines = ["DRAFT SUSPICIOUS ACTIVITY REPORT - NOT FILED - requires authorized human review",
             f"Case #{case.id} | Subject: {cust.name if cust else 'unknown'} | Country: {cust.country if cust else 'n/a'}", "",
             "Screening matches (potential only, not proof of wrongdoing):"]
    lines += [f" - {m['matched_name']} [{m['list']}] confidence {m['confidence']}" for m in case.matches] or [" - none recorded"]
    lines += ["", "Reviewer notes:"] + [f" - {n['ts'][:10]} {n['by']}: {n['text']}" for n in case.notes] or [" - none"]
    lines += ["", "Transaction references (most recent flagged):"] + [f" - {t.id} {t.ts:%Y-%m-%d %H:%M} {float(t.amount):,.2f} {t.currency} {t.merchant} [{t.severity}]" for t in txns]
    missing = [x for x, ok in [("Reviewer notes", bool(case.notes)), ("Transaction evidence", bool(txns)), ("Source of funds", bool(cust and cust.source_of_funds))] if not ok]
    lines += ["", "Missing information: " + (", ".join(missing) or "none identified"), "Status: DRAFT (version %d)" % (len(case.sar_drafts or []) + 1)]
    return "\n".join(lines)
