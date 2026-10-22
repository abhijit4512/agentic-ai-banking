# FinPilot AI (demo build)

Agentic banking demo: dashboard, KYC/AML screening, fraud rules, customer-service assistant, loan underwriting, and PDF document RAG with citations.
Runs fully offline in **DEMO MODE** with synthetic data. An LLM is optional (see `.env.example`).

## Requirements
Python 3.10+ and Node.js 18+ (nodejs.org LTS).

## 1. Backend  (PowerShell)
```powershell
cd finpilot-ai\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
copy ..\.env.example .env         # optional; defaults work
uvicorn app.main:app --reload --port 8000
```
macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, then the same pip/uvicorn lines.
First start creates the SQLite DB, seeds demo data and a sample PDF. API docs: http://localhost:8000/docs

## 2. Frontend (second terminal)
```powershell
cd finpilot-ai\frontend
npm install
npm run dev
```
Open http://localhost:5173

## Demo logins (password `Demo@12345`)
admin@finpilot.demo · analyst@finpilot.demo · underwriter@finpilot.demo · customer@finpilot.demo

## Tests
```powershell
cd backend
pip install -r requirements-dev.txt
pytest --cov=app
```
Covers loan maths, RAG helpers, KYC flows, JWT/revocation, a role x endpoint authorization matrix, the audit hash chain, every fraud rule (boundaries and combinations), idempotency and key rotation.

## Run with Docker (Postgres + API + web)
```sh
cp .env.example .env        # then set JWT_SECRET_KEY and KYC_ENCRYPTION_KEY (see comments in the file)
docker compose up --build   # web on http://localhost:8080
```
Set `DEMO_MODE=false` in `.env` to hide demo credentials in the UI build and disable self-registration.

> **Upgrading an existing local SQLite database:** this version adds columns to `audit_logs` and two new tables. The project still uses `create_all` (no migrations), so delete `backend/data/finpilot.db` once and restart to re-seed.

## Try the RAG flow
AI Document Assistant -> sample_lending_policy.pdf is preloaded. Ask: "total amount in the statement", "show the table with loan eligibility criteria", "show the image on page 3". Upload your own PDF too.

## KYC document portal
Sign in as `customer@finpilot.demo` or create a sandbox customer account on the login screen to submit KYC documents at **KYC Documents**. Public self-registration is deliberately disabled outside demo mode until email verification is integrated. Staff with the `admin` or `analyst` role can review submissions there. Supported uploads are PDF, JPG, JPEG, and PNG, subject to `MAX_UPLOAD_SIZE_MB`; PDFs are limited to 20 pages. Files are encrypted on disk and are only served through authenticated, customer-scoped API routes. PDF previews are rendered to protected page images.

The module performs file checks, optional OCR, conservative labeled-field extraction, basic format/expiry checks, and cross-document mismatch warnings. These checks are informational and do **not** verify issuer authenticity, identity, or Aadhaar authentication. A human reviewer must make decisions. OCR is disabled by default; if enabled, scanned PDFs and images are sent to the configured Hugging Face model. Test model compatibility and data-processing permissions before enabling it.

New API routes (all under `/api/v1`):

- `GET /kyc/me`, `PATCH /kyc/profile`
- `POST /auth/register` (demo mode only; creates a customer account without email verification)
- `POST /kyc/documents` (multipart fields: `file`, `document_type`, optional `supersedes_id`)
- `POST /kyc/documents/{id}/retry-ocr`, `GET /kyc/documents/{id}/file` (authenticated attachment), `GET /kyc/documents/{id}/preview?page=1` (authenticated rendered preview)
- `GET /kyc/applications`, `GET /kyc/applications/{customer_id}`, `GET /kyc/stats` (admin/analyst only)
- `GET /kyc/documents/{id}/review`, `POST /kyc/documents/{id}/corrections`, `/decision`, and `/escalate` (admin/analyst only; full extracted text is available only through the per-document review route)
- `POST /kyc/documents/{id}/corrections`, `/decision`, and `/escalate` (admin/analyst only)

KYC settings are read from environment variables by the backend process:

- `KYC_ENCRYPTION_KEY`: use a stable, secret key in production. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Back it up securely; changing or losing it makes stored KYC files and extracted information unreadable.** Demo mode derives a key from `JWT_SECRET_KEY` when this is blank.
- `KYC_OCR_ENABLED`: defaults to `false`. Set to `true` only after reviewing the external data transfer and provider permissions.
- `HF_TOKEN`, `HF_OCR_MODEL`: token and image-to-text model repository supported by the Hugging Face Inference API. A missing or failing provider is reported; OCR is never presented as successful in that case.
- `OCR_TIMEOUT`: per-request timeout in seconds. Up to two retries are used for transient timeouts and model-loading responses.
- `MAX_UPLOAD_SIZE_MB`: shared upload limit (default 25 MB).
- Production startup requires `APP_ENV=production`, `DEMO_MODE=false`, a unique `JWT_SECRET_KEY` of at least 32 characters, and `KYC_ENCRYPTION_KEY`. Use HTTPS, a production-grade secret manager, private backups, retention/deletion controls, and a configured issuer-verification provider before onboarding real customers.

For PowerShell, configure variables in the same terminal before starting the backend, for example:
```powershell
$env:KYC_ENCRYPTION_KEY = "<generated Fernet key>"
$env:KYC_OCR_ENABLED = "false"
uvicorn app.main:app --reload --port 8000
```

The current app uses SQLAlchemy `create_all`, not migrations; startup creates the new KYC table without replacing existing tables. Keep development secrets out of production, serve production over HTTPS, configure encrypted/private backups and retention/deletion controls, add malware scanning and distributed rate limiting, and complete legal/security review before handling real customer identity documents. This demo is not a compliance certification or production-ready banking system.

## Implemented vs simulated vs missing
- Working: auth + roles, customer scoping, audit log, fraud rules + alerts + simulator, two-person simulated hold, synthetic AML screening + cases + draft-only SAR, support tools, Decimal loan maths + policy checks + human decision, PDF ingest (text, tables, page images), BM25 retrieval, table/total/image answers with citations, prompt-injection line filter, private encrypted KYC document intake, reviewer audit/correction workflow, and manual KYC decisions.
- Simulated: sanctions/PEP data, core banking, credit bureau (none fabricated), account holds.
- Not included (needs work/integrations): KYC issuer verification, production identity proofing, malware scanning, production key management, formal retention/deletion workflows, OCR model credentials/compatibility testing, ChromaDB/embeddings (BM25 used instead), Alembic migrations (tables auto-created), Postgres (set DATABASE_URL), streaming chat, distributed rate limiting, frontend tests, TanStack Query/Tailwind/shadcn, real SAR filing.


## Production-hardening update

| Area | What changed |
|---|---|
| Auth | PyJWT tokens with `iss/aud/iat/exp/jti` + token type; real server-side logout (revocation by `jti`); image URLs use a 15-minute image-only media token instead of the session token; lockout after repeated failed logins; optional `X-Forwarded-For` trust (`TRUST_PROXY`) |
| Audit | Append-only, hash-chained log; `GET /api/v1/audit-logs/verify` (admin) detects edits or deletions |
| Data | Fraud rules use `Decimal`; money input is `Decimal`; transaction ids no longer rely on `count()+1`; `Idempotency-Key` on `POST /transactions/events` |
| Crypto | KYC encryption uses `MultiFernet` (comma-separated keys, first encrypts) and PBKDF2 for non-Fernet secrets; old data stays readable |
| Authorization | `release` needs an existing hold; staff support chat needs an explicit `customer_id`; `reprocess` is staff-only |
| Ops | `/api/v1/ready` (DB + storage), request ids, security headers, access logs without query strings, FastAPI lifespan, no deprecated `utcnow()`, PDFs closed after use |
| Frontend | `window.prompt()` replaced by an accessible dialog; error boundary; role-based route guards; status bar uses real `/ready` data (no hard-coded uptime); demo credentials only when `VITE_DEMO_MODE=true` |
| Tooling | Dockerfiles + docker-compose (Postgres), GitHub Actions CI (ruff, pytest+coverage, build, gitleaks, pip-audit, npm audit), pre-commit, `SECURITY.md` |

**Still not production-ready** (see `SECURITY.md`): tokens live in `localStorage` (no httpOnly cookies/CSRF yet), rate limiting is in-memory (no Redis), no MFA/password reset/email verification, no Alembic migrations, `main.py` is not yet split into routers, OCR/ingestion still run in the request, RAG still uses BM25, TypeScript is not in strict mode, there are no frontend tests, and screening data is synthetic.
