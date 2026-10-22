import os, hmac, hashlib, time, uuid
import jwt
from dotenv import load_dotenv
load_dotenv()
SECRET = os.getenv("JWT_SECRET_KEY", "dev-only-change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/finpilot.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIRECTORY", "./data/uploads")
MAX_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "25"))
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_OCR_MODEL = os.getenv("HF_OCR_MODEL", "")
KYC_OCR_ENABLED = os.getenv("KYC_OCR_ENABLED", "false").lower() == "true"
OCR_TIMEOUT = float(os.getenv("OCR_TIMEOUT", "30"))
# One key, or several comma-separated keys. The FIRST key encrypts; all keys can decrypt (rotation).
KYC_ENCRYPTION_KEY = os.getenv("KYC_ENCRYPTION_KEY", "")
ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
DEMO = os.getenv("DEMO_MODE", "true").lower() == "true"
ENV = os.getenv("APP_ENV", "development")
LLM_KEY = os.getenv("LLM_API_KEY", "")
LLM_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
# Only trust X-Forwarded-For when the API really sits behind your own reverse proxy.
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_SECONDS = int(os.getenv("LOGIN_LOCKOUT_SECONDS", "900"))

JWT_ISSUER = "finpilot-api"
JWT_AUDIENCE = "finpilot-web"
ACCESS_TTL = 8 * 3600
MEDIA_TTL = 15 * 60  # short-lived token that may ONLY be used to load page images


def hash_pw(p, salt=None):
    salt = salt or os.urandom(16).hex()
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), 200_000).hex()


def check_pw(p, stored):
    return hmac.compare_digest(hash_pw(p, stored.split("$")[0]), stored)


def make_token(uid, role, ttl=ACCESS_TTL, typ="access"):
    """Signed JWT (HS256) with iss/aud/iat/exp/jti. 'u' and 'r' keep the old claim names."""
    now = int(time.time())
    payload = {"u": uid, "r": role, "typ": typ, "iss": JWT_ISSUER, "aud": JWT_AUDIENCE,
               "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, SECRET, algorithm="HS256")


def read_token(t, typ="access"):
    """Return the verified payload, or None for anything invalid, expired or of the wrong type."""
    try:
        p = jwt.decode(t, SECRET, algorithms=["HS256"], audience=JWT_AUDIENCE, issuer=JWT_ISSUER,
                       options={"require": ["exp", "iat", "jti", "iss", "aud"]})
        return p if p.get("typ") == typ else None
    except Exception:
        return None


def client_ip(request):
    """Client IP for rate limiting. Honors X-Forwarded-For only when TRUST_PROXY is enabled."""
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
