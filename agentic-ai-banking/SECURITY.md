# Security

FinPilot AI is a **demo / portfolio project** and is not certified for handling real customer identity documents.

## What is implemented
- JWT (HS256) with `iss`, `aud`, `iat`, `exp`, `jti` and a token type; server-side revocation on logout.
- `?token=` URLs accept only 15-minute **media tokens**, and only for page-image routes.
- Login rate limit per IP, account lockout after repeated failures, optional `X-Forwarded-For` trust (`TRUST_PROXY`).
- KYC files and extracted data are Fernet-encrypted at rest; `KYC_ENCRYPTION_KEY` accepts several comma-separated keys for rotation (first encrypts, all decrypt).
- Append-only, hash-chained audit log; `GET /api/v1/audit-logs/verify` (admin) detects edited or removed rows.
- Role checks on every route plus customer scoping; two-person rule for simulated fraud holds.
- Secrets live only in untracked `.env` files; CI runs gitleaks and dependency audits.

## Known gaps (do before real use)
- Tokens are still kept in `localStorage` (move to httpOnly cookies + CSRF protection).
- Rate limiting and lockout are in-memory (per process); use Redis for multiple workers.
- No password reset, email verification or MFA. Self-registration is disabled outside demo mode for that reason.
- No migrations (Alembic) - the schema is created with `create_all`. Existing SQLite files from older versions must be deleted and reseeded.
- No malware scanning, retention or deletion workflow for uploaded documents.
- Sanctions screening data is synthetic; no real issuer/identity verification is performed.

## Rotating the KYC key
1. Generate a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Set `KYC_ENCRYPTION_KEY=<new>,<old>` and restart. New writes use `<new>`; old data still decrypts.
3. Re-encrypt old records, then drop `<old>`.

## Reporting a vulnerability
Open a private security advisory on the repository rather than a public issue.
