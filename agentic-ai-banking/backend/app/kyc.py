import base64
import hashlib
import io
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path

import fitz
import httpx
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from functools import lru_cache
from PIL import Image, ImageOps

from . import core
DOCUMENT_TYPES = {
    "aadhaar": "Aadhaar card",
    "pan": "PAN card",
    "passport": "Passport",
    "driving_licence": "Driving licence",
    "voter_id": "Voter ID",
    "bank_statement": "Bank statement",
    "utility_bill": "Utility bill",
    "other": "Other identity/address document",
}
STATUSES = (
    "Uploaded", "Processing", "Pending Review", "Verified", "Rejected",
    "Resubmission Required", "Verification Failed",
)
MAX_PDF_PAGES = 20
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


class KycError(Exception):
    def __init__(self, message, status_code=400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _is_fernet_key(value):
    try:
        return len(base64.urlsafe_b64decode(value.encode())) == 32
    except Exception:
        return False


@lru_cache(maxsize=16)
def _build_cipher(secrets):
    """MultiFernet: the FIRST key encrypts, every key can decrypt (key rotation).
    A proper Fernet key is used as-is; any other string is stretched with PBKDF2 (demo/dev convenience).
    The old SHA-256 derivation is kept as a decrypt-only fallback so existing demo data stays readable."""
    fernets = []
    for secret in secrets:
        if _is_fernet_key(secret):
            fernets.append(Fernet(secret.encode()))
        else:
            derived = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"finpilot-kyc-v2", 200_000, dklen=32)
            fernets.append(Fernet(base64.urlsafe_b64encode(derived)))
            legacy = hashlib.sha256(secret.encode() + b":finpilot-kyc").digest()
            fernets.append(Fernet(base64.urlsafe_b64encode(legacy)))
    return MultiFernet(fernets)


def _cipher():
    if core.ENV.lower() == "production" and not core.KYC_ENCRYPTION_KEY:
        raise RuntimeError("KYC_ENCRYPTION_KEY must be configured in production.")
    secrets = tuple(k.strip() for k in (core.KYC_ENCRYPTION_KEY or core.SECRET).split(",") if k.strip())
    return _build_cipher(secrets)


def encrypt_text(value):
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value):
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise RuntimeError("Stored KYC data could not be decrypted; check KYC_ENCRYPTION_KEY.") from exc


def decrypt_json(value, default):
    return json.loads(decrypt_text(value)) if value else default


def validate_upload(filename, data):
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise KycError("Upload a PDF, JPG, JPEG, or PNG file.", 415)
    if len(data) > core.MAX_MB * 1024 * 1024:
        raise KycError(f"File exceeds the {core.MAX_MB} MB upload limit.", 413)
    if not data:
        raise KycError("The selected file is empty.", 422)
    if suffix not in (".pdf",) and (data.startswith(b"%PDF-") or
            (suffix == ".png" and data.startswith(b"\xff\xd8\xff")) or
            (suffix in (".jpg", ".jpeg") and data.startswith(b"\x89PNG\r\n\x1a\n"))):
        raise KycError("The file extension does not match the document content.", 415)
    try:
        if suffix == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise KycError("The file extension does not match a valid PDF.", 415)
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if pdf.is_encrypted:
                    raise KycError("Password-protected PDFs are not supported.", 422)
                if not 1 <= len(pdf) <= MAX_PDF_PAGES:
                    raise KycError(f"PDFs must contain between 1 and {MAX_PDF_PAGES} pages.", 422)
            return "application/pdf"
        expected = "JPEG" if suffix in (".jpg", ".jpeg") else "PNG"
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > 30_000_000:
            raise KycError("The image dimensions exceed the supported limit.", 413)
        image.verify()
        image = Image.open(io.BytesIO(data))
        if image.format != expected:
            raise KycError("The file extension does not match the image content.", 415)
        return "image/jpeg" if expected == "JPEG" else "image/png"
    except KycError:
        raise
    except (fitz.FileDataError, fitz.EmptyFileError, OSError, Image.DecompressionBombError) as exc:
        raise KycError("The document is damaged or could not be read.", 422) from exc


def _ocr_image(image_bytes):
    if not core.KYC_OCR_ENABLED:
        raise KycError("/p OCR is disabled. An authorized reviewer can inspect the document manually./p", 503)
    if not core.HF_TOKEN or not core.HF_OCR_MODEL:
        raise KycError("OCR is enabled but HF_TOKEN or HF_OCR_MODEL is not configured.", 503)
    url = "https://router.huggingface.co/hf-inference/models/" + core.HF_OCR_MODEL
    headers = {"Authorization": "Bearer " + core.HF_TOKEN, "Content-Type": "application/octet-stream"}
    for attempt in range(3):
        try:
            response = httpx.post(url, content=image_bytes, headers=headers, timeout=core.OCR_TIMEOUT)
        except httpx.TimeoutException as exc:
            if attempt == 2:
                raise KycError("OCR provider timed out. Please retry or request manual review.", 503) from exc
            time.sleep(attempt + 1)
            continue
        except httpx.RequestError as exc:
            if attempt == 2:
                raise KycError("OCR provider is unavailable. Please retry or request manual review.", 503) from exc
            time.sleep(attempt + 1)
            continue
        if response.status_code == 503 and attempt < 2:
            time.sleep(attempt + 1)
            continue
        if response.status_code >= 400:
            raise KycError(f"OCR provider returned HTTP {response.status_code}. Please retry or request manual review.", 503)
        try:
            result = response.json()
        except ValueError as exc:
            raise KycError("OCR provider returned an unsupported response.", 503) from exc
        if isinstance(result, list):
            text = " ".join(str(item.get("generated_text", item.get("text", ""))) for item in result if isinstance(item, dict))
        elif isinstance(result, dict):
            text = str(result.get("generated_text", result.get("text", "")))
        else:
            text = ""
        if not text.strip():
            raise KycError("OCR did not return readable text. Please retry or request manual review.", 422)
        return text.strip()
    raise KycError("OCR provider is unavailable. Please retry or request manual review.", 503)


def extract_text(data, mime_type):
    if mime_type == "application/pdf":
        text = []
        with fitz.open(stream=data, filetype="pdf") as pdf:
            for index, page in enumerate(pdf):
                page_text = page.get_text().strip()
                if len(page_text) < 10:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
                    page_text = _ocr_image(pixmap.tobytes("png"))
                text.append(f"[Page {index + 1}]\n{page_text}")
        return "\n\n".join(text)
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return _ocr_image(output.getvalue())


def _capture(text, label_pattern):
    match = re.search(label_pattern + r"\s*[:\-]\s*([^\r\n]{1,120})", text, re.I)
    return match.group(1).strip() if match else None


def _normalized_date(value):
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return value


def extract_fields(text, document_type):
    fields = {}
    labels = {
        "name": r"(?:full\s+)?name(?:\s+of\s+(?:holder|customer|applicant))?",
        "date_of_birth": r"(?:date\s+of\s+birth|dob|birth\s+date)",
        "address": r"(?:residential\s+)?address",
        "gender": r"gender",
        "nationality": r"nationality",
        "father_name": r"(?:father'?s?\s+name|father)",
        "bank_name": r"(?:bank\s+name|name\s+of\s+bank)",
        "issuer": r"(?:issuer|issued\s+by|utility\s+provider)",
        "bill_date": r"(?:bill\s+date|statement\s+date|date\s+of\s+issue)",
        "expiry_date": r"(?:expiry\s+date|date\s+of\s+expiry|valid\s+(?:until|till))",
        "account_number": r"(?:account\s+(?:number|no\.?))",
        "statement_period": r"(?:statement\s+period|period)",
        "issue_date": r"(?:issue\s+date|date\s+of\s+issue)",
    }
    for key, pattern in labels.items():
        value = _capture(text, pattern)
        if value:
            normalized = _normalized_date(value) if key in ("date_of_birth", "bill_date", "expiry_date", "issue_date") else value
            fields[key] = {"value": value, "normalized": normalized, "confidence": None, "source": "label_match"}
    numbers = {
        "aadhaar": ("identity_number", r"\b(?:\d{4}[\s-]?){2}\d{4}\b"),
        "pan": ("identity_number", r"\b[A-Z]{5}\d{4}[A-Z]\b"),
        "passport": ("identity_number", r"\b[A-Z][0-9]{7}\b"),
        "driving_licence": ("identity_number", r"\b[A-Z]{2}[- ]?\d{2}[- ]?\d{4}[- ]?\d{7,}\b"),
        "voter_id": ("identity_number", r"\b[A-Z]{3}[0-9]{7}\b"),
    }
    if document_type in numbers:
        key, pattern = numbers[document_type]
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(0).strip()
            fields[key] = {"value": value, "normalized": re.sub(r"[\s-]", "", value).upper(), "confidence": None, "source": "format_match"}
    return fields


def validate_fields(fields, document_type):
    required = {
        "aadhaar": ("name", "identity_number"),
        "pan": ("name", "identity_number"),
        "passport": ("name", "identity_number", "date_of_birth"),
        "driving_licence": ("name", "identity_number"),
        "voter_id": ("name", "identity_number"),
        "bank_statement": ("name", "bank_name", "statement_period"),
        "utility_bill": ("name", "address", "bill_date"),
        "other": ("name",),
    }[document_type]
    missing = [name for name in required if name not in fields]
    warnings = ["Format checks and OCR do not establish document authenticity or identity."]
    checks = {"required_fields_present": not missing, "missing_fields": missing, "warnings": warnings,
              "format_checks": [], "processing_errors": [],
              "issuer_verification": {"status": "Not Configured", "provider": None}}
    identity = fields.get("identity_number", {}).get("value", "")
    if document_type == "pan" and identity:
        valid = bool(re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", identity, re.I))
        checks["format_checks"].append({"check": "PAN format", "passed": valid})
    elif document_type == "aadhaar" and identity:
        valid = len(re.sub(r"\D", "", identity)) == 12
        checks["format_checks"].append({"check": "Aadhaar number format", "passed": valid})
    expiry = fields.get("expiry_date", {}).get("value", "")
    if expiry:
        parsed = None
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
            try:
                parsed = datetime.strptime(expiry.strip(), fmt).date()
                break
            except ValueError:
                continue
        if parsed:
            expired = parsed < date.today()
            checks["format_checks"].append({"check": "Expiry date", "passed": not expired, "expired": expired})
            if expired:
                warnings.append("The extracted expiry date appears to be in the past.")
        else:
            warnings.append("Expiry date was extracted but could not be interpreted.")
    if missing:
        warnings.append("Some expected fields were not found in the extracted text.")
    return checks


def cross_document_warnings(documents):
    groups = {}
    identities = {}
    superseded_ids = {doc.supersedes_id for doc in documents if doc.supersedes_id is not None}
    for doc in documents:
        if doc.id in superseded_ids:
            continue
        fields = decrypt_json(doc.extracted_fields, {})
        for key in ("name", "date_of_birth"):
            value = fields.get(key, {}).get("normalized") or fields.get(key, {}).get("value")
            if value:
                groups.setdefault(key, []).append((doc.id, str(value).casefold().strip()))
        address = fields.get("address", {}).get("normalized") or fields.get("address", {}).get("value")
        if address:
            groups.setdefault("address", []).append((doc.id, re.sub(r"\s+", " ", str(address).casefold()).strip()))
        identity = fields.get("identity_number", {}).get("normalized") or fields.get("identity_number", {}).get("value")
        if identity:
            identities.setdefault(doc.document_type, []).append((doc.id, str(identity).casefold().strip()))
    mismatches = []
    for key, values in groups.items():
        if len(values) > 1 and len({value for _, value in values}) > 1:
            mismatches.append({"field": key, "document_ids": [doc_id for doc_id, _ in values], "warning": "Values differ across submitted documents."})
    for document_type, values in identities.items():
        if len(values) > 1 and len({value for _, value in values}) > 1:
            mismatches.append({"field": f"{document_type}_number", "document_ids": [doc_id for doc_id, _ in values],
                               "warning": "Different identity numbers appear on documents of the same type."})
    return mismatches


def save_encrypted_file(data, customer_id):
    directory = Path(core.UPLOAD_DIR).resolve() / "private_kyc" / str(customer_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (os.urandom(16).hex() + ".enc")
    path.write_bytes(_cipher().encrypt(data))
    return str(path)


def read_encrypted_file(path):
    try:
        return _cipher().decrypt(Path(path).read_bytes())
    except (OSError, InvalidToken) as exc:
        raise RuntimeError("Stored KYC document could not be read; check KYC_ENCRYPTION_KEY.") from exc


def content_hash(data):
    return hashlib.sha256(data).hexdigest()


def customer_fields(doc):
    fields = decrypt_json(doc.extracted_fields, {})
    for key, item in fields.items():
        if key in ("identity_number", "account_number", "passport_number", "licence_number"):
            value = item.get("value", "")
            digits = re.sub(r"\W", "", value)
            item["value"] = ("*" * max(0, len(digits) - 4)) + digits[-4:] if digits else ""
            item["normalized"] = item["value"]
    return fields


def serialize_document(doc, reviewer=False):
    result = {
        "id": doc.id, "customer_id": doc.customer_id, "document_type": doc.document_type,
        "document_label": DOCUMENT_TYPES.get(doc.document_type, "Document"),
        "name": decrypt_text(doc.original_filename), "mime_type": doc.mime_type, "size": doc.file_size,
        "status": doc.status, "validation": doc.validation or {}, "pages": doc.page_count or 1,
        "customer_message": doc.customer_message or "", "created_at": doc.created_at.isoformat(),
        "supersedes_id": doc.supersedes_id,
    }
    result["fields"] = decrypt_json(doc.extracted_fields, {}) if reviewer else customer_fields(doc)
    if reviewer:
        result["extracted_text"] = decrypt_text(doc.extracted_text or "")
        result["reviewer_notes"] = decrypt_text(doc.reviewer_notes or "")
        result["review_history"] = decrypt_json(doc.review_history, [])
        result["preview_url"] = f"/kyc/documents/{doc.id}/file"
    return result


def store_extraction(doc, text):
    fields = extract_fields(text, doc.document_type)
    doc.extracted_text = encrypt_text(text)
    doc.extracted_fields = encrypt_text(json.dumps(fields, ensure_ascii=False))
    doc.validation = validate_fields(fields, doc.document_type)
    doc.status = "Pending Review"
    doc.customer_message = "Document received. Automated checks are informational; an authorized reviewer must make the decision."
