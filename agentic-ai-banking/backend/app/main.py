import os, re, time, uuid, random, json, logging, contextlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
import fitz
from sqlalchemy import text as sql_text
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from . import core, models as M, rules, loans, rag, support, seed, compliance, kyc
from . import audit as auditlog
from .db import Base, engine, Session
from .models import row, now as utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("finpilot")

STAFF = ("admin", "analyst", "underwriter")
_kyc_upload_hits = {}

def startup():
    if core.ENV.lower() == "production":
        if core.DEMO:
            raise RuntimeError("DEMO_MODE must be false in production.")
        if len(core.SECRET) < 32 or core.SECRET == "dev-only-change-me":
            raise RuntimeError("Set a unique JWT_SECRET_KEY of at least 32 characters in production.")
        if not core.KYC_ENCRYPTION_KEY:
            raise RuntimeError("Set KYC_ENCRYPTION_KEY before starting in production.")
    os.makedirs(core.UPLOAD_DIR, exist_ok=True); Base.metadata.create_all(engine)
    with Session() as db:
        if not db.query(M.User).count(): seed.run(db)

@contextlib.asynccontextmanager
async def lifespan(_app):
    startup()
    yield

app = FastAPI(title="FinPilot AI", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[core.ORIGIN], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def request_context(request: Request, call_next):
    """Request id + security headers + access log. Logs the path only (never the query string, which could hold a token)."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.time()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    log.info("request_id=%s method=%s path=%s status=%s ms=%d", rid, request.method, request.url.path,
             response.status_code, (time.time() - started) * 1000)
    return response

def get_db():
    db = Session()
    try: yield db
    finally: db.close()

def user(request: Request, authorization: str = Header(None), db=Depends(get_db)):
    header = authorization or ""
    if header.lower().startswith("bearer "):
        p = core.read_token(header[7:].strip())
    elif request.method == "GET" and "/pages/" in request.url.path and request.query_params.get("token"):
        p = core.read_token(request.query_params["token"], typ="media")  # <img> tags cannot send headers
    else:
        p = None
    if p and db.get(M.RevokedToken, p["jti"]): p = None  # logged out
    u = p and db.get(M.User, p["u"])
    if not u: raise HTTPException(401, "Not authenticated")
    request.state.token = p
    return u

def need(*roles):
    def dep(u=Depends(user)):
        if u.role not in roles: raise HTTPException(403, "Insufficient role")
        return u
    return dep

def audit(db, u, action, detail=""):
    auditlog.add_entry(db, u.email if u else "anonymous", action, detail); db.commit()

def scoped(q, u, col): return q.filter(col == u.customer_id) if u.role == "customer" else q
def get_or_404(db, model, id):
    o = db.get(model, id)
    if not o: raise HTTPException(404, "Not found")
    return o

# ---------- platform / auth ----------
@app.get("/api/v1/health")
def health(): return {"status": "ok", "demo_mode": core.DEMO, "env": core.ENV, "llm_configured": bool(core.LLM_KEY and core.LLM_URL)}

@app.get("/api/v1/ready")
def ready(db=Depends(get_db)):
    """Readiness probe: checks the database and upload storage. 503 when degraded."""
    checks = {}
    try: db.execute(sql_text("SELECT 1")); checks["database"] = "ok"
    except Exception: checks["database"] = "error"
    try:
        os.makedirs(core.UPLOAD_DIR, exist_ok=True); probe = os.path.join(core.UPLOAD_DIR, ".ready")
        open(probe, "w").close(); os.remove(probe); checks["storage"] = "ok"
    except Exception: checks["storage"] = "error"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks, "demo_mode": core.DEMO, "env": core.ENV}, status_code=200 if ok else 503)

class LoginIn(BaseModel): email: str; password: str
_hits = {}
_lock = {}  # email -> {"n": consecutive failures, "until": lockout expiry}

def lock_remaining(email):
    r = _lock.get(email)
    if not r or not r["until"]: return 0
    left = r["until"] - time.time()
    if left <= 0: _lock.pop(email, None); return 0
    return int(left) + 1

def note_failure(email):
    if len(_lock) > 10000: _lock.clear()
    r = _lock.setdefault(email, {"n": 0, "until": 0}); r["n"] += 1
    if r["n"] >= core.LOGIN_MAX_FAILURES: r["until"] = time.time() + core.LOGIN_LOCKOUT_SECONDS; r["n"] = 0
@app.post("/api/v1/auth/login")
def login(b: LoginIn, request: Request, db=Depends(get_db)):
    ip = core.client_ip(request); w = [t for t in _hits.get(ip, []) if time.time() - t < 60]
    if len(w) >= 10: raise HTTPException(429, "Too many attempts, wait a minute")
    _hits[ip] = w + [time.time()]
    email = b.email.lower().strip()
    if lock_remaining(email):
        audit(db, None, "login_locked", email); raise HTTPException(429, "Too many failed attempts. Try again later.")
    u = db.query(M.User).filter_by(email=email).first()
    if not u or not core.check_pw(b.password, u.pw):
        note_failure(email); audit(db, None, "login_failed", email); raise HTTPException(401, "Invalid email or password")
    _lock.pop(email, None)
    audit(db, u, "login")
    return {"token": core.make_token(u.id, u.role), "user": row(u, ("pw",))}

class RegisterIn(BaseModel):
    email: str
    name: str
    password: str
    country: str = "IN"

_registration_hits = {}
@app.post("/api/v1/auth/register", status_code=201)
def register(b: RegisterIn, request: Request, db=Depends(get_db)):
    if not core.DEMO:
        raise HTTPException(404, "Self-registration is disabled until email verification is configured")
    ip = core.client_ip(request)
    now = time.time()
    recent = [stamp for stamp in _registration_hits.get(ip, []) if now - stamp < 3600]
    if len(recent) >= 3:
        raise HTTPException(429, "Registration limit reached. Please try again later.")
    _registration_hits[ip] = recent + [now]
    email = b.email.strip().lower()
    name = b.name.strip()
    country = b.country.strip().upper()
    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}", email) or len(email) > 254:
        raise HTTPException(422, "Enter a valid email address")
    if not name or len(name) > 160:
        raise HTTPException(422, "Name must be between 1 and 160 characters")
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise HTTPException(422, "Country must be a two-letter ISO code")
    if (len(b.password) < 12 or len(b.password) > 128 or not re.search(r"[a-z]", b.password) or
            not re.search(r"[A-Z]", b.password) or not re.search(r"\d", b.password) or
            not re.search(r"[^A-Za-z0-9]", b.password)):
        raise HTTPException(422, "Password must be 12–128 characters and include upper/lowercase letters, a number, and a symbol")
    if db.query(M.User).filter_by(email=email).first():
        raise HTTPException(409, "An account with this email already exists")
    customer = M.Customer(name=name, type="individual", country=country, occupation="",
                          source_of_funds="", account="DEMO-" + uuid.uuid4().hex[:10].upper(),
                          kyc_status="pending")
    db.add(customer)
    db.flush()
    new_user = M.User(email=email, name=name, role="customer", pw=core.hash_pw(b.password),
                      customer_id=customer.id)
    db.add(new_user)
    db.commit()
    audit(db, new_user, "customer_registered", f"customer:{customer.id}")
    return {"token": core.make_token(new_user.id, new_user.role), "user": row(new_user, ("pw",)),
            "note": "Demo account created. Email verification and production identity checks are not configured."}

@app.post("/api/v1/auth/logout")
def logout(request: Request, db=Depends(get_db), u=Depends(user)):
    p = request.state.token
    if not db.get(M.RevokedToken, p["jti"]): db.add(M.RevokedToken(jti=p["jti"], expires=int(p["exp"])))
    db.query(M.RevokedToken).filter(M.RevokedToken.expires < int(time.time())).delete()  # purge expired entries
    db.commit(); audit(db, u, "logout")
    return {"ok": True, "note": "Token revoked server-side."}

@app.post("/api/v1/auth/media-token")
def media_token(u=Depends(user)):
    """Short-lived token that is only accepted for GET /documents/{id}/pages/{n} (used by <img> tags)."""
    return {"token": core.make_token(u.id, u.role, ttl=core.MEDIA_TTL, typ="media"), "expires_in": core.MEDIA_TTL}
@app.get("/api/v1/auth/me")
def me(u=Depends(user)): return row(u, ("pw",))

@app.get("/api/v1/audit-logs")
def audit_logs(limit: int = 200, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    return [row(a) for a in db.query(M.AuditLog).order_by(M.AuditLog.id.desc()).limit(min(limit, 500))]

@app.get("/api/v1/audit-logs/verify")
def audit_verify(db=Depends(get_db), u=Depends(need("admin"))):
    """Re-computes the hash chain; ok=false means a row was altered or removed."""
    return auditlog.verify_chain(db)

@app.get("/api/v1/notifications")
def notifications(db=Depends(get_db), u=Depends(need(*STAFF))):
    a = db.query(M.Alert).filter(M.Alert.status == "open", M.Alert.severity.in_(["high", "critical"])).order_by(M.Alert.id.desc()).limit(10)
    return [{"id": x.id, "text": f"{x.severity.upper()} alert on {x.txn_id}"} for x in a]

# ---------- dashboard ----------
@app.get("/api/v1/dashboard/summary")
def summary(db=Depends(get_db), u=Depends(need(*STAFF))):
    T = M.Transaction
    kyc = {}
    for c in db.query(M.Customer): kyc[c.kyc_status] = kyc.get(c.kyc_status, 0) + 1
    days = {}
    for t in db.query(T).filter(T.ts >= utcnow() - timedelta(days=30)).order_by(T.ts):
        d = days.setdefault(t.ts.strftime("%m-%d"), {"date": t.ts.strftime("%m-%d"), "count": 0, "flagged": 0}); d["count"] += 1; d["flagged"] += t.status == "flagged"
    buckets = {"0": 0, "1-39": 0, "40-59": 0, "60-79": 0, "80-100": 0}
    types = {}
    for s, ty in db.query(T.score, T.type):
        buckets["0" if s == 0 else "1-39" if s < 40 else "40-59" if s < 60 else "60-79" if s < 80 else "80-100"] += 1; types[ty] = types.get(ty, 0) + 1
    return {"total_transactions": db.query(T).count(), "flagged": db.query(T).filter(T.status == "flagged").count(),
            "open_cases": db.query(M.Case).filter(M.Case.status.in_(["open", "escalated"])).count(),
            "alerts_by_severity": {s: db.query(M.Alert).filter(M.Alert.severity == s).count() for s in ("low", "medium", "high", "critical")},
            "pending_loans": db.query(M.Loan).filter(M.Loan.status.in_(["submitted", "documents_pending", "under_review"])).count(),
            "kyc": [{"name": k, "value": v} for k, v in kyc.items()], "trend": list(days.values()),
            "risk_distribution": [{"name": k, "value": v} for k, v in buckets.items()], "by_type": [{"name": k, "value": v} for k, v in types.items()],
            "recent_activity": [row(a) for a in db.query(M.AuditLog).order_by(M.AuditLog.id.desc()).limit(8)]}

# ---------- transactions ----------
@app.get("/api/v1/transactions")
def list_txns(limit: int = 300, status: Optional[str] = None, db=Depends(get_db), u=Depends(user)):
    q = scoped(db.query(M.Transaction), u, M.Transaction.customer_id)
    if status: q = q.filter(M.Transaction.status == status)
    return [row(t) for t in q.order_by(M.Transaction.ts.desc()).limit(min(limit, 1000))]

@app.get("/api/v1/transactions/{tid}")
def get_txn(tid: str, db=Depends(get_db), u=Depends(user)):
    t = get_or_404(db, M.Transaction, tid)
    if u.role == "customer" and t.customer_id != u.customer_id: raise HTTPException(404, "Not found")
    hist = db.query(M.Transaction).filter_by(account=t.account).order_by(M.Transaction.ts.desc()).limit(10)
    return {**row(t), "history": [row(h) for h in hist], "alerts": [row(a) for a in db.query(M.Alert).filter_by(txn_id=t.id)]}

class TxnIn(BaseModel):
    account: str; amount: Decimal; currency: str = "USD"; type: str = "card"; merchant: str = "Unknown"
    channel: str = "web"; country: Optional[str] = None; status: str = "completed"

@app.post("/api/v1/transactions/events", status_code=201)
def txn_event(b: TxnIn, idempotency_key: Optional[str] = Header(None), db=Depends(get_db), u=Depends(need(*STAFF))):
    """Send an Idempotency-Key header to make retries safe: a repeated key returns the original transaction."""
    if b.amount <= 0: raise HTTPException(422, "amount must be positive")
    if idempotency_key:
        if len(idempotency_key) > 128: raise HTTPException(422, "Idempotency-Key is too long")
        prior = db.query(M.IdempotencyKey).filter_by(key=idempotency_key, actor=u.email).first()
        if prior: return row(get_or_404(db, M.Transaction, prior.txn_id))
    c = db.query(M.Customer).filter_by(account=b.account).first()
    if not c: raise HTTPException(404, "Unknown account")
    t = rules.ingest_txn(db, customer_id=c.id, **b.model_dump())
    if idempotency_key: db.add(M.IdempotencyKey(key=idempotency_key, actor=u.email, txn_id=t.id))
    db.commit(); audit(db, u, "txn_event", t.id)
    return row(t)

@app.post("/api/v1/transactions/simulate")
def simulate(n: int = 10, db=Depends(get_db), u=Depends(need(*STAFF))):
    cs = db.query(M.Customer).all(); out = []
    for _ in range(min(n, 50)):
        c = random.choice(cs); big = random.random() < .2
        t = rules.ingest_txn(db, customer_id=c.id, account=c.account, amount=round(random.uniform(10000, 30000) if big else random.uniform(10, 300), 2), type=random.choice(["card", "transfer", "wire"]),
                             merchant=random.choice(["Grocery Mart", "Crypto Exchange", "Online Store", "Offshore Holdings"]), channel="web", country=random.choice([c.country, c.country, "BR", "RO"]), status=random.choice(["completed"] * 8 + ["failed"]))
        out.append(t.id)
    db.commit(); audit(db, u, "simulate", f"{len(out)} events"); return {"created": out}

# ---------- fraud ----------
@app.get("/api/v1/fraud/alerts")
def alerts(status: Optional[str] = None, db=Depends(get_db), u=Depends(need(*STAFF))):
    q = db.query(M.Alert)
    if status: q = q.filter(M.Alert.status == status)
    out = []
    for a in q.order_by(M.Alert.id.desc()).limit(300):
        t = db.get(M.Transaction, a.txn_id); out.append({**row(a), "amount": float(t.amount), "account": t.account, "merchant": t.merchant, "ts": t.ts.isoformat()})
    return out

@app.get("/api/v1/fraud/alerts/{aid}")
def alert_detail(aid: int, db=Depends(get_db), u=Depends(need(*STAFF))):
    a = get_or_404(db, M.Alert, aid); return {**row(a), "transaction": get_txn(a.txn_id, db, u), "customer": row(db.get(M.Customer, a.customer_id))}

class ReviewIn(BaseModel): status: str; note: str = ""; assignee: Optional[str] = None
@app.post("/api/v1/fraud/alerts/{aid}/review")
def alert_review(aid: int, b: ReviewIn, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    if b.status not in ("open", "investigating", "resolved_fraud", "resolved_false_positive"): raise HTTPException(422, "Invalid status")
    a = get_or_404(db, M.Alert, aid); a.status = b.status; a.assignee = b.assignee or a.assignee
    a.notes = (a.notes or []) + [{"ts": utcnow().isoformat(), "by": u.email, "text": b.note}]; db.commit(); audit(db, u, "alert_review", f"{aid}->{b.status}"); return row(a)

class ActionIn(BaseModel): action: str; reason: str
@app.post("/api/v1/fraud/alerts/{aid}/action")
def alert_action(aid: int, b: ActionIn, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    """DEMO: simulated hold only. Two-person rule: analyst requests, admin approves."""
    a = get_or_404(db, M.Alert, aid)
    if not b.reason.strip(): raise HTTPException(422, "A reason is required")
    if b.action == "request_hold": a.action_state = "pending_approval"
    elif b.action == "approve_hold":
        if u.role != "admin": raise HTTPException(403, "Only an admin can approve a hold")
        if a.action_state != "pending_approval": raise HTTPException(409, "No hold awaiting approval")
        a.action_state = "hold_simulated"
    elif b.action == "release":
        if a.action_state not in ("pending_approval", "hold_simulated"): raise HTTPException(409, "There is no hold to release")
        a.action_state = "released"
    else: raise HTTPException(422, "Unknown action")
    db.commit(); audit(db, u, "alert_action", f"{aid} {b.action}: {b.reason}"); return {"alert_id": aid, "action_state": a.action_state, "simulated": True}

# ---------- compliance ----------
class CustIn(BaseModel): name: str; type: str = "individual"; country: str; occupation: str = ""; source_of_funds: str = ""
@app.post("/api/v1/compliance/customers", status_code=201)
def new_customer(b: CustIn, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    c = M.Customer(**b.model_dump(), account=f"ACC-{1000 + db.query(M.Customer).count() + 1}", kyc_status="pending"); db.add(c); db.flush()
    m = compliance.screen(c.name, c.country); case = None
    if m: case = M.Case(customer_id=c.id, kind="screening", matches=m); db.add(case)
    db.commit(); audit(db, u, "customer_onboarded", c.name)
    return {"customer": row(c), "matches": m, "case_id": case.id if case else None, "note": "KYC stays 'pending' until a human verifies identity documents."}

class ScreenIn(BaseModel): name: str; country: Optional[str] = None
@app.post("/api/v1/compliance/screen")
def screen(b: ScreenIn, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    audit(db, u, "screen", b.name); return {"matches": compliance.screen(b.name, b.country), "screened_at": utcnow().isoformat(), "source": "synthetic demo dataset", "disclaimer": "A potential match is not proof of wrongdoing. Human review required."}

@app.get("/api/v1/compliance/cases")
def cases(db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    return [{**row(c), "customer": db.get(M.Customer, c.customer_id).name} for c in db.query(M.Case).order_by(M.Case.id.desc())]
@app.get("/api/v1/compliance/cases/{cid}")
def case_detail(cid: int, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    c = get_or_404(db, M.Case, cid); return {**row(c), "customer": row(db.get(M.Customer, c.customer_id))}

class CaseReview(BaseModel): outcome: str; note: str
@app.post("/api/v1/compliance/cases/{cid}/review")
def case_review(cid: int, b: CaseReview, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    st = {"false_positive": "closed_false_positive", "escalate": "escalated", "confirmed": "confirmed"}.get(b.outcome)
    if not st or not b.note.strip(): raise HTTPException(422, "Valid outcome and a reviewer note are required")
    c = get_or_404(db, M.Case, cid); c.status = st; c.notes = (c.notes or []) + [{"ts": utcnow().isoformat(), "by": u.email, "text": b.note}]
    db.commit(); audit(db, u, "case_review", f"{cid}->{st}"); return row(c)

@app.post("/api/v1/compliance/cases/{cid}/sar-draft")
def sar(cid: int, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    c = get_or_404(db, M.Case, cid); cu = db.get(M.Customer, c.customer_id)
    tx = db.query(M.Transaction).filter_by(customer_id=c.customer_id, status="flagged").order_by(M.Transaction.ts.desc()).limit(10).all()
    text = compliance.sar_draft(c, cu, tx); c.sar_drafts = (c.sar_drafts or []) + [{"ts": utcnow().isoformat(), "by": u.email, "text": text}]
    db.commit(); audit(db, u, "sar_draft", cid); return {"status": "DRAFT - not filed", "version": len(c.sar_drafts), "text": text}

# ---------- support ----------
class ChatIn(BaseModel): message: str; customer_id: Optional[int] = None
@app.post("/api/v1/support/chat")
def chat(b: ChatIn, db=Depends(get_db), u=Depends(user)):
    if u.role == "customer": cid = u.customer_id   # customers can never choose another customer
    elif b.customer_id is None: raise HTTPException(422, "customer_id is required for staff users")
    else: cid = b.customer_id
    r = support.chat(db, cid, b.message); audit(db, u, "support_chat", b.message[:80]); return r
@app.get("/api/v1/support/conversations")
def conversations(db=Depends(get_db), u=Depends(user)):
    return [row(a) for a in db.query(M.AuditLog).filter_by(actor=u.email, action="support_chat").order_by(M.AuditLog.id.desc()).limit(30)]
class DisputeIn(BaseModel): txn_id: str; reason: str
@app.post("/api/v1/support/disputes", status_code=201)
def dispute(b: DisputeIn, db=Depends(get_db), u=Depends(user)):
    t = get_or_404(db, M.Transaction, b.txn_id)
    if u.role == "customer" and t.customer_id != u.customer_id: raise HTTPException(404, "Not found")
    d = M.Dispute(customer_id=t.customer_id, txn_id=t.id, reason=b.reason); db.add(d); db.commit(); audit(db, u, "dispute_created", d.id); return row(d)
@app.get("/api/v1/support/disputes/{did}")
def dispute_get(did: int, db=Depends(get_db), u=Depends(user)):
    d = get_or_404(db, M.Dispute, did)
    if u.role == "customer" and d.customer_id != u.customer_id: raise HTTPException(404, "Not found")
    return row(d)

# ---------- loans ----------
class LoanIn(BaseModel):
    customer_id: Optional[int] = None; applicant: str; loan_type: str = "personal"; amount: float; term_months: int
    rate: float = 11.5; income: float; debt: float = 0; employment: str = "salaried"
@app.post("/api/v1/loans/applications", status_code=201)
def loan_new(b: LoanIn, db=Depends(get_db), u=Depends(user)):
    if b.amount <= 0 or b.term_months <= 0 or b.income <= 0 or b.debt < 0: raise HTTPException(422, "Amount, term and income must be positive")
    d = b.model_dump(); d["customer_id"] = u.customer_id if u.role == "customer" else d["customer_id"]
    l = M.Loan(**d, docs=[]); db.add(l); db.commit(); audit(db, u, "loan_created", l.id); return row(l)
@app.get("/api/v1/loans/applications")
def loan_list(db=Depends(get_db), u=Depends(user)):
    return [row(l) for l in scoped(db.query(M.Loan), u, M.Loan.customer_id).order_by(M.Loan.id.desc())]
def own_loan(db, u, lid):
    l = get_or_404(db, M.Loan, lid)
    if u.role == "customer" and l.customer_id != u.customer_id: raise HTTPException(404, "Not found")
    return l
@app.get("/api/v1/loans/applications/{lid}")
def loan_get(lid: int, db=Depends(get_db), u=Depends(user)):
    l = own_loan(db, u, lid); return {**row(l), "schedule": loans.schedule(l.amount, l.rate, l.term_months)}
class LoanDoc(BaseModel): doc_type: str; document_id: Optional[int] = None
@app.post("/api/v1/loans/applications/{lid}/documents")
def loan_doc(lid: int, b: LoanDoc, db=Depends(get_db), u=Depends(user)):
    l = own_loan(db, u, lid)
    if b.document_id and not db.get(M.Document, b.document_id): raise HTTPException(404, "Document not found")
    l.docs = (l.docs or []) + [{"doc_type": b.doc_type, "document_id": b.document_id, "verified": False}]; db.commit(); return row(l)
@app.post("/api/v1/loans/applications/{lid}/assess")
def loan_assess(lid: int, db=Depends(get_db), u=Depends(need("admin", "underwriter", "analyst"))):
    l = get_or_404(db, M.Loan, lid); a = loans.assess(l); l.assessment = a
    if l.status in ("submitted", "documents_pending", "under_review", "recommended_approval", "recommended_rejection"): l.status = a["suggested_status"]
    db.commit(); audit(db, u, "loan_assessed", f"{lid} {l.status}"); return a
class DecisionIn(BaseModel): decision: str; note: str
@app.post("/api/v1/loans/applications/{lid}/decision")
def loan_decision(lid: int, b: DecisionIn, db=Depends(get_db), u=Depends(need("admin", "underwriter"))):
    if b.decision not in ("approved", "rejected") or len(b.note.strip()) < 5: raise HTTPException(422, "Decision (approved/rejected) and a written explanation are required")
    l = get_or_404(db, M.Loan, lid)
    if not l.assessment: raise HTTPException(409, "Run the assessment first")
    l.status = b.decision; l.decision_note = f"{u.email}: {b.note}"; db.commit(); audit(db, u, "loan_decision", f"{lid} {b.decision}"); return row(l)

# ---------- documents & RAG ----------
def doc_ok(db, u, did):
    d = get_or_404(db, M.Document, did)
    if u.role == "customer" and d.owner_id != u.id: raise HTTPException(404, "Not found")
    return d
@app.post("/api/v1/documents/upload", status_code=201)
async def upload(file: UploadFile = File(...), db=Depends(get_db), u=Depends(user)):
    data = await file.read()
    if not (file.filename or "").lower().endswith(".pdf") or not data.startswith(b"%PDF"): raise HTTPException(415, "Only valid PDF files are accepted")
    if len(data) > core.MAX_MB * 1024 * 1024: raise HTTPException(413, f"File exceeds {core.MAX_MB} MB")
    path = os.path.join(core.UPLOAD_DIR, uuid.uuid4().hex + ".pdf")
    with open(path, "wb") as f: f.write(data)
    d = M.Document(name=os.path.basename(file.filename), owner_id=u.id, path=path); db.add(d); db.flush()
    try: rag.ingest(db, d)
    except Exception as e: d.status = "failed"; d.note = f"Processing failed: {e}"
    db.commit(); audit(db, u, "document_upload", d.name); return row(d, ("path",))
@app.get("/api/v1/documents")
def docs(db=Depends(get_db), u=Depends(user)):
    q = db.query(M.Document)
    if u.role == "customer": q = q.filter(M.Document.owner_id == u.id)
    return [row(d, ("path",)) for d in q.order_by(M.Document.id.desc())]
@app.get("/api/v1/documents/{did}")
def doc_get(did: int, db=Depends(get_db), u=Depends(user)): return row(doc_ok(db, u, did), ("path",))
@app.get("/api/v1/documents/{did}/pages/{n}")
def page_img(did: int, n: int, db=Depends(get_db), u=Depends(user)):
    d = doc_ok(db, u, did)
    if n < 1 or n > d.pages: raise HTTPException(404, "Page out of range")
    with fitz.open(d.path) as pdf:
        png = pdf[n - 1].get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})
@app.get("/api/v1/documents/{did}/tables")
def doc_tables(did: int, db=Depends(get_db), u=Depends(user)):
    doc_ok(db, u, did); return [row(t) for t in db.query(M.Tbl).filter_by(doc_id=did)]
@app.get("/api/v1/documents/{did}/images")
def doc_images(did: int, db=Depends(get_db), u=Depends(user)):
    d = doc_ok(db, u, did); return [{"page": i, "url": f"/documents/{did}/pages/{i}"} for i in range(1, d.pages + 1)]
@app.post("/api/v1/documents/{did}/reprocess")
def reprocess(did: int, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    d = doc_ok(db, u, did); db.query(M.Chunk).filter_by(doc_id=did).delete(); db.query(M.Tbl).filter_by(doc_id=did).delete(); rag.ingest(db, d); db.commit(); return row(d, ("path",))
class RagIn(BaseModel): question: str; document_ids: Optional[list[int]] = None
@app.post("/api/v1/rag/query")
def rag_query(b: RagIn, db=Depends(get_db), u=Depends(user)):
    q = db.query(M.Document.id)
    if u.role == "customer": q = q.filter(M.Document.owner_id == u.id)
    allowed = {i for (i,) in q}; ids = [i for i in (b.document_ids or allowed) if i in allowed]
    if not ids: raise HTTPException(404, "No accessible documents selected")
    audit(db, u, "rag_query", b.question[:80]); return rag.query(db, b.question, ids)

# ---------- customer KYC ----------
def kyc_customer_id(u):
    if u.role != "customer" or u.customer_id is None:
        raise HTTPException(403, "A linked customer profile is required")
    return u.customer_id

def kyc_document(db, document_id, u, reviewer=False):
    d = db.get(M.KycDocument, document_id)
    if not d: raise HTTPException(404, "KYC document not found")
    if not reviewer and (u.role != "customer" or d.customer_id != u.customer_id):
        raise HTTPException(404, "KYC document not found")
    return d

def kyc_progress(db, customer_id):
    documents = db.query(M.KycDocument).filter_by(customer_id=customer_id).all()
    ids = {"aadhaar", "pan", "passport", "driving_licence", "voter_id"}
    addresses = ids | {"bank_statement", "utility_bill"}
    has_identity = any(d.document_type in ids and d.status == "Verified" for d in documents)
    has_address = any(d.document_type in addresses and d.status == "Verified" and
                      kyc.decrypt_json(d.extracted_fields, {}).get("address", {}).get("value")
                      for d in documents)
    return {"required_categories": 2, "completed_categories": int(has_identity) + int(has_address),
            "completion_percent": round((int(has_identity) + int(has_address)) * 50),
            "identity_document": has_identity, "proof_of_address": has_address}

@app.get("/api/v1/kyc/me")
def kyc_me(db=Depends(get_db), u=Depends(user)):
    customer_id = kyc_customer_id(u)
    customer = get_or_404(db, M.Customer, customer_id)
    documents = db.query(M.KycDocument).filter_by(customer_id=customer_id).order_by(M.KycDocument.id.desc()).all()
    return {"profile": {"name": customer.name, "country": customer.country, "occupation": customer.occupation,
                        "source_of_funds": customer.source_of_funds, "kyc_status": customer.kyc_status},
            "progress": kyc_progress(db, customer_id),
            "documents": [kyc.serialize_document(d) for d in documents]}

@app.get("/api/v1/kyc/stats")
def kyc_stats(db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    documents = db.query(M.KycDocument)
    total = documents.count()
    counts = {status: documents.filter(M.KycDocument.status == status).count() for status in kyc.STATUSES}
    return {"total_documents": total, "by_status": counts,
            "human_reviewed": counts["Verified"] + counts["Rejected"] + counts["Resubmission Required"],
            "ocr_or_processing_failures": counts["Verification Failed"],
            "human_review_rate_percent": round(100 * (counts["Verified"] + counts["Rejected"] + counts["Resubmission Required"]) / total) if total else 0}

class KycProfileIn(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    occupation: Optional[str] = None
    source_of_funds: Optional[str] = None

@app.patch("/api/v1/kyc/profile")
def kyc_profile(b: KycProfileIn, db=Depends(get_db), u=Depends(user)):
    customer = get_or_404(db, M.Customer, kyc_customer_id(u))
    values = b.model_dump(exclude_unset=True)
    for key, value in values.items():
        value = (value or "").strip()
        if key == "name" and not value:
            raise HTTPException(422, "Name cannot be empty")
        if key == "country":
            value = value.upper()
            if not re.fullmatch(r"[A-Z]{2}", value):
                raise HTTPException(422, "Country must be a two-letter ISO code")
        if len(value) > 160:
            raise HTTPException(422, f"{key.replace('_', ' ').capitalize()} is too long")
        setattr(customer, key, value)
    db.commit()
    audit(db, u, "kyc_profile_updated", f"customer:{customer.id}")
    return {"name": customer.name, "country": customer.country, "occupation": customer.occupation,
            "source_of_funds": customer.source_of_funds}

def pdf_page_count(data):
    with fitz.open(stream=data, filetype="pdf") as pdf:
        return len(pdf)

@app.post("/api/v1/kyc/documents", status_code=201)
def kyc_upload(file: UploadFile = File(...), document_type: str = Form(...),
               supersedes_id: Optional[int] = Form(None), db=Depends(get_db), u=Depends(user)):
    customer_id = kyc_customer_id(u)
    now = time.time()
    recent_uploads = [stamp for stamp in _kyc_upload_hits.get(u.id, []) if now - stamp < 3600]
    if len(recent_uploads) >= 20:
        raise HTTPException(429, "Upload limit reached. Please try again later.")
    _kyc_upload_hits[u.id] = recent_uploads + [now]
    if document_type not in kyc.DOCUMENT_TYPES:
        raise HTTPException(422, "Unsupported KYC document type")
    data = file.file.read(core.MAX_MB * 1024 * 1024 + 1)
    try:
        mime_type = kyc.validate_upload(file.filename, data)
    except kyc.KycError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    digest = kyc.content_hash(data)
    duplicate = db.query(M.KycDocument).filter_by(customer_id=customer_id, sha256=digest).first()
    if duplicate:
        raise HTTPException(409, "This document was already submitted. Use the existing submission or upload a corrected file.")
    previous = None
    if supersedes_id is not None:
        previous = kyc_document(db, supersedes_id, u)
        if previous.customer_id != customer_id or previous.document_type != document_type:
            raise HTTPException(404, "The document to replace was not found")
    try:
        stored_path = kyc.save_encrypted_file(data, customer_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    filename = (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1][:200] or "document"
    doc = M.KycDocument(customer_id=customer_id, uploaded_by=u.id, document_type=document_type,
                        original_filename=kyc.encrypt_text(filename), stored_path=stored_path,
                        mime_type=mime_type, file_size=len(data), sha256=digest, status="Processing",
                        supersedes_id=previous.id if previous else None,
                        page_count=pdf_page_count(data) if mime_type == "application/pdf" else 1)
    db.add(doc)
    db.flush()
    try:
        text = kyc.extract_text(data, mime_type)
        kyc.store_extraction(doc, text)
    except kyc.KycError as exc:
        doc.status = "Verification Failed" if exc.status_code != 503 else "Pending Review"
        doc.customer_message = exc.message
        doc.validation = {"required_fields_present": False, "missing_fields": [],
                          "warnings": ["Automated extraction was not completed; no verification decision was made."],
                          "processing_errors": [exc.message],
                          "issuer_verification": {"status": "Not Configured", "provider": None}}
    if previous:
        previous.status = "Resubmission Required"
        previous.customer_message = "A replacement document was submitted. This earlier version is retained in the submission history."
    db.commit()
    audit(db, u, "kyc_document_uploaded", f"document:{doc.id};customer:{customer_id}")
    return kyc.serialize_document(doc)

@app.post("/api/v1/kyc/documents/{document_id}/retry-ocr")
def kyc_retry_ocr(document_id: int, db=Depends(get_db), u=Depends(user)):
    doc = kyc_document(db, document_id, u, reviewer=u.role in ("admin", "analyst"))
    if doc.status in ("Verified", "Rejected"):
        raise HTTPException(409, "A final reviewer decision has already been recorded")
    try:
        data = kyc.read_encrypted_file(doc.stored_path)
        doc.status = "Processing"
        text = kyc.extract_text(data, doc.mime_type)
        kyc.store_extraction(doc, text)
    except kyc.KycError as exc:
        doc.status = "Verification Failed"
        doc.customer_message = exc.message
        doc.validation = {"required_fields_present": False, "missing_fields": [],
                          "warnings": ["Automated extraction was not completed; no verification decision was made."],
                          "processing_errors": [exc.message],
                          "issuer_verification": {"status": "Not Configured", "provider": None}}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    doc.updated_at = utcnow()
    db.commit()
    audit(db, u, "kyc_ocr_retried", f"document:{doc.id}")
    return kyc.serialize_document(doc, reviewer=u.role in ("admin", "analyst"))

@app.get("/api/v1/kyc/documents/{document_id}/file")
def kyc_file(document_id: int, db=Depends(get_db), u=Depends(user)):
    doc = kyc_document(db, document_id, u, reviewer=u.role in ("admin", "analyst"))
    try:
        data = kyc.read_encrypted_file(doc.stored_path)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="kyc-document-{doc.id}.bin"',
                             "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

@app.get("/api/v1/kyc/documents/{document_id}/preview")
def kyc_preview(document_id: int, page: int = 1, db=Depends(get_db), u=Depends(user)):
    doc = kyc_document(db, document_id, u, reviewer=u.role in ("admin", "analyst"))
    try:
        data = kyc.read_encrypted_file(doc.stored_path)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if doc.mime_type == "application/pdf":
        try:
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if page < 1 or page > len(pdf):
                    raise HTTPException(404, "Page out of range")
                data = pdf[page - 1].get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False).tobytes("png")
        except (fitz.FileDataError, fitz.EmptyFileError) as exc:
            raise HTTPException(422, "The stored PDF could not be previewed") from exc
        mime_type = "image/png"
    else:
        mime_type = doc.mime_type
    return Response(data, media_type=mime_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Security-Policy": "default-src 'none'; sandbox"})

@app.get("/api/v1/kyc/applications")
def kyc_applications(status: Optional[str] = None, q: str = "", offset: int = 0, limit: int = 25,
                     db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    if status and status not in kyc.STATUSES:
        raise HTTPException(422, "Unknown KYC status")
    query = db.query(M.Customer)
    if q.strip():
        query = query.filter(M.Customer.name.ilike("%" + q.strip()[:80] + "%"))
    if status:
        matching_customers = db.query(M.KycDocument.customer_id).filter_by(status=status).distinct()
        query = query.filter(M.Customer.id.in_(matching_customers))
    total = query.count()
    customers = query.order_by(M.Customer.id.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 100)).all()
    applications = []
    for customer in customers:
        documents = db.query(M.KycDocument).filter_by(customer_id=customer.id).order_by(M.KycDocument.id.desc()).all()
        applications.append({"customer_id": customer.id, "customer_name": customer.name,
                             "kyc_status": customer.kyc_status, "progress": kyc_progress(db, customer.id),
                             "documents": [kyc.serialize_document(doc) for doc in documents],
                             "mismatches": kyc.cross_document_warnings(documents)})
    return {"applications": applications, "total": total, "offset": max(offset, 0), "limit": min(max(limit, 1), 100)}

@app.get("/api/v1/kyc/applications/{customer_id}")
def kyc_application(customer_id: int, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    customer = get_or_404(db, M.Customer, customer_id)
    documents = db.query(M.KycDocument).filter_by(customer_id=customer.id).order_by(M.KycDocument.id.desc()).all()
    return {"customer_id": customer.id, "customer_name": customer.name, "kyc_status": customer.kyc_status,
            "progress": kyc_progress(db, customer.id),
            "documents": [kyc.serialize_document(doc) for doc in documents],
            "mismatches": kyc.cross_document_warnings(documents)}

@app.get("/api/v1/kyc/documents/{document_id}/review")
def kyc_review_document(document_id: int, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    doc = kyc_document(db, document_id, u, reviewer=True)
    return kyc.serialize_document(doc, reviewer=True)

class KycCorrectionIn(BaseModel):
    fields: dict[str, str]
    reason: str

@app.post("/api/v1/kyc/documents/{document_id}/corrections")
def kyc_corrections(document_id: int, b: KycCorrectionIn, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    doc = kyc_document(db, document_id, u, reviewer=True)
    if len(b.reason.strip()) < 5 or not b.fields:
        raise HTTPException(422, "Provide corrected fields and a reason of at least five characters")
    allowed = {"name", "date_of_birth", "address", "gender", "nationality", "father_name", "bank_name",
               "issuer", "bill_date", "expiry_date", "account_number", "statement_period", "issue_date",
               "identity_number"}
    if any(key not in allowed or len(value) > 500 for key, value in b.fields.items()):
        raise HTTPException(422, "Unsupported field or correction is too long")
    values = kyc.decrypt_json(doc.extracted_fields, {})
    history = kyc.decrypt_json(doc.review_history, [])
    corrected = {}
    for key, value in b.fields.items():
        value = value.strip()
        corrected[key] = {"value": value, "normalized": value, "confidence": None, "source": "reviewer"}
        values[key] = corrected[key]
    history.append({"action": "correction", "by": u.email, "at": utcnow().isoformat(),
                    "reason": b.reason.strip(), "fields": corrected})
    doc.extracted_fields = kyc.encrypt_text(json.dumps(values, ensure_ascii=False))
    doc.review_history = kyc.encrypt_text(json.dumps(history, ensure_ascii=False))
    doc.validation = kyc.validate_fields(values, doc.document_type)
    doc.status = "Pending Review"
    doc.updated_at = utcnow()
    db.commit()
    audit(db, u, "kyc_fields_corrected", f"document:{doc.id}")
    return kyc.serialize_document(doc, reviewer=True)

class KycDecisionIn(BaseModel):
    status: str
    reason: str
    customer_message: str = ""

@app.post("/api/v1/kyc/documents/{document_id}/decision")
def kyc_decision(document_id: int, b: KycDecisionIn, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    allowed = ("Pending Review", "Verified", "Rejected", "Resubmission Required")
    if b.status not in allowed or len(b.reason.strip()) < 5:
        raise HTTPException(422, "Choose a valid review outcome and provide a reason of at least five characters")
    if b.status in ("Rejected", "Resubmission Required") and len(b.customer_message.strip()) < 5:
        raise HTTPException(422, "Provide customer-facing resubmission instructions without internal reviewer notes")
    doc = kyc_document(db, document_id, u, reviewer=True)
    history = kyc.decrypt_json(doc.review_history, [])
    history.append({"action": "decision", "status": b.status, "by": u.email, "at": utcnow().isoformat(),
                    "reason": b.reason.strip()})
    doc.review_history = kyc.encrypt_text(json.dumps(history, ensure_ascii=False))
    doc.reviewer_notes = kyc.encrypt_text(b.reason.strip())
    doc.status = b.status
    doc.customer_message = (b.customer_message.strip() or "Your document review status was updated. Contact support if you need assistance.")[:500]
    doc.reviewed_by = u.email
    doc.reviewed_at = utcnow()
    doc.updated_at = utcnow()
    docs = db.query(M.KycDocument).filter_by(customer_id=doc.customer_id).all()
    identity_types = {"aadhaar", "pan", "passport", "driving_licence", "voter_id"}
    address_types = identity_types | {"bank_statement", "utility_bill"}
    has_identity = any(item.document_type in identity_types and item.status == "Verified" for item in docs if item.id != doc.id) or (doc.document_type in identity_types and doc.status == "Verified")
    has_address = any(item.document_type in address_types and item.status == "Verified" and
                      kyc.decrypt_json(item.extracted_fields, {}).get("address", {}).get("value")
                      for item in docs if item.id != doc.id) or (doc.document_type in address_types and
                      doc.status == "Verified" and kyc.decrypt_json(doc.extracted_fields, {}).get("address", {}).get("value"))
    customer = db.get(M.Customer, doc.customer_id)
    customer.kyc_status = "verified" if has_identity and has_address else "rejected" if b.status == "Rejected" else "pending"
    db.commit()
    audit(db, u, "kyc_document_decision", f"document:{doc.id};status:{doc.status};customer:{doc.customer_id}")
    return {"document": kyc.serialize_document(doc, reviewer=True), "progress": kyc_progress(db, doc.customer_id)}

class KycEscalationIn(BaseModel):
    reason: str

@app.post("/api/v1/kyc/documents/{document_id}/escalate")
def kyc_escalate(document_id: int, b: KycEscalationIn, db=Depends(get_db), u=Depends(need("admin", "analyst"))):
    if len(b.reason.strip()) < 5:
        raise HTTPException(422, "An escalation reason of at least five characters is required")
    doc = kyc_document(db, document_id, u, reviewer=True)
    history = kyc.decrypt_json(doc.review_history, [])
    history.append({"action": "escalation", "by": u.email, "at": utcnow().isoformat(),
                    "reason": b.reason.strip()})
    doc.review_history = kyc.encrypt_text(json.dumps(history, ensure_ascii=False))
    doc.reviewer_notes = kyc.encrypt_text(b.reason.strip())
    doc.status = "Pending Review"
    doc.customer_message = "Your document has been referred for additional review."
    doc.reviewed_by = u.email
    doc.reviewed_at = utcnow()
    doc.updated_at = utcnow()
    db.commit()
    audit(db, u, "kyc_document_escalated", f"document:{doc.id};customer:{doc.customer_id}")
    return kyc.serialize_document(doc, reviewer=True)
