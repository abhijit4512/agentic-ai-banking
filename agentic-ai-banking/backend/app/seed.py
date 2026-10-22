import random, os, fitz
from datetime import datetime, timedelta
from . import core, compliance, rules, rag, audit
from .models import *
from .models import now as utcnow
pw = core.hash_pw("Demo@12345")

def draw_table(p, x, y, rows, widths, h=22):
    for i, r in enumerate(rows):
        cx = x
        for c, w in zip(r, widths):
            rect = fitz.Rect(cx, y + i * h, cx + w, y + (i + 1) * h); p.draw_rect(rect, width=.8)
            p.insert_textbox(rect + (3, 5, -3, -1), c, fontsize=9, fontname="hebo" if i == 0 else "helv"); cx += w

def sample_pdf(path):
    d = fitz.open(); p = d.new_page()
    p.insert_text((50, 60), "Retail Lending Policy 2026 (synthetic demo)", fontsize=16)
    p.insert_text((50, 90), "Table 1: Loan eligibility criteria", fontsize=11)
    draw_table(p, 50, 100, [["Loan type", "Min income (USD/month)", "Max DTI", "Max term (months)"], ["Personal", "2,500", "43%", "60"], ["Auto", "3,000", "40%", "72"], ["Home", "4,000", "36%", "360"]], [110, 150, 80, 120])
    p.insert_text((50, 230), "Personal loans carry a 11.5% APR. Applicants must provide income proof, a bank statement and identity.", fontsize=10)
    p = d.new_page(); p.insert_text((50, 60), "Account Statement - January 2026", fontsize=16)
    draw_table(p, 50, 90, [["Date", "Description", "Amount (USD)"], ["2026-01-03", "Salary credit", "3,200.00"], ["2026-01-05", "Rent", "-1,100.00"], ["2026-01-09", "Groceries", "-210.45"], ["2026-01-15", "Utilities", "-96.30"]], [110, 200, 120])
    p = d.new_page(); p.insert_text((50, 60), "Figure 1: Monthly loan disbursements (chart)", fontsize=14)
    p.insert_text((50, 85), "Transaction process: customer applies, documents are verified, underwriter reviews, decision is issued.", fontsize=9)
    for i, (m, v) in enumerate([("Jan", 90), ("Feb", 140), ("Mar", 120), ("Apr", 190)]):
        r = fitz.Rect(70 + i * 90, 330 - v, 120 + i * 90, 330); p.draw_rect(r, fill=(0.1, 0.35, 0.8)); p.insert_text((85 + i * 90, 345), m, fontsize=10)
    d.save(path)

def run(db):
    random.seed(7)
    C = [("Aarav Mehta", "individual", "IN", "Software engineer", "Salary"), ("Priya Nair", "individual", "IN", "Boutique owner", "Business income"),
         ("Northwind Trading FZE", "business", "AE", "Import/export", "Trade receipts"), ("Daniel Okafor", "individual", "NG", "Consultant", "Consulting fees"),
         ("Sofia Rossi", "individual", "IT", "Teacher", "Salary")]
    cs = []
    for i, (n, t, c, o, s) in enumerate(C, 1):
        cu = Customer(name=n, type=t, country=c, occupation=o, source_of_funds=s, account=f"ACC-{1000+i}", kyc_status="verified" if i in (1, 5) else "pending"); db.add(cu); cs.append(cu)
    db.flush()
    for e, n, r, cid in [("admin@finpilot.demo", "Alex Admin", "admin", None), ("analyst@finpilot.demo", "Anna Analyst", "analyst", None),
                         ("underwriter@finpilot.demo", "Uma Underwriter", "underwriter", None), ("customer@finpilot.demo", "Aarav Mehta", "customer", cs[0].id), ("customer2@finpilot.demo", "Priya Nair", "customer", cs[1].id)]:
        db.add(User(email=e, name=n, role=r, pw=pw, customer_id=cid))
    now = utcnow(); merchants = ["Grocery Mart", "Fuel Station", "Cafe Aroma", "Online Store", "Utility Co", "Pharmacy", "Streaming Svc"]
    for cu in cs:
        for k in range(50):
            rules.ingest_txn(db, ts=now - timedelta(days=random.uniform(1, 30)), customer_id=cu.id, account=cu.account, amount=round(random.lognormvariate(4.5, .7), 2),
                             type=random.choice(["card", "transfer", "upi"]), merchant=random.choice(merchants), channel=random.choice(["pos", "web", "mobile"]), country=cu.country)
    db.flush(); t0 = now - timedelta(hours=3)
    for k in range(6):
        rules.ingest_txn(db, ts=t0 + timedelta(minutes=k), customer_id=cs[1].id, account=cs[1].account, amount=9500 + k * 10, type="transfer", merchant="New Beneficiary", channel="web", country="IN")
    rules.ingest_txn(db, ts=now - timedelta(hours=1), customer_id=cs[2].id, account=cs[2].account, amount=48000, type="wire", merchant="Offshore Holdings", channel="web", country="PA")
    for k in range(4):
        rules.ingest_txn(db, ts=now - timedelta(minutes=40 - k * 3), customer_id=cs[3].id, account=cs[3].account, amount=500, type="card", merchant="Crypto Exchange", channel="web", country="NG", status="failed")
    for cu in cs:
        m = compliance.screen(cu.name, cu.country)
        if m: db.add(Case(customer_id=cu.id, kind="screening", matches=m))
    for cid, a, y, t, r in [(cs[0].id, "Aarav Mehta", "personal", 15000, 48), (cs[3].id, "Daniel Okafor", "auto", 40000, 60)]:
        db.add(Loan(customer_id=cid, applicant=a, loan_type=y, amount=t, term_months=r, rate=11.5, income=4200, debt=900, employment="salaried", docs=[]))
    db.flush()
    path = os.path.join(core.UPLOAD_DIR, "sample_lending_policy.pdf"); os.makedirs(core.UPLOAD_DIR, exist_ok=True); sample_pdf(path)
    d = Document(name="sample_lending_policy.pdf", owner_id=1, path=path); db.add(d); db.flush(); rag.ingest(db, d)
    audit.add_entry(db, "system", "seed", "Synthetic demo data loaded"); db.commit()
