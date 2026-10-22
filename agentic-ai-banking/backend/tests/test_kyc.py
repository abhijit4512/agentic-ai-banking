import io
import json
from types import SimpleNamespace

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import core, kyc, main
from app.db import Base
from app.models import Customer, KycDocument, User


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")
    return output.getvalue()


def pdf_bytes(text="Synthetic KYC test"):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((40, 40), text)
    return pdf.tobytes()


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db:
        customer = Customer(name="Synthetic Person", type="individual", country="IN", occupation="Tester",
                            source_of_funds="Synthetic", account="TEST-1")
        other_customer = Customer(name="Other Person", type="individual", country="IN", occupation="Tester",
                                  source_of_funds="Synthetic", account="TEST-2")
        db.add_all([customer, other_customer])
        db.flush()
        customer_id, other_customer_id = customer.id, other_customer.id
        db.add_all([
            User(email="customer@test.invalid", name="Synthetic Person", role="customer", pw="",
                 customer_id=customer_id),
            User(email="other@test.invalid", name="Other Person", role="customer", pw="",
                 customer_id=other_customer_id),
            User(email="reviewer@test.invalid", name="Reviewer", role="admin", pw="", customer_id=None),
        ])
        db.commit()
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "Session", testing_session)
    monkeypatch.setattr(core, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(core, "KYC_ENCRYPTION_KEY", "test-key-used-only-in-tests")
    monkeypatch.setattr(core, "KYC_OCR_ENABLED", False)
    with TestClient(main.app) as test_client:
        test_client.customer_id = customer_id
        test_client.other_customer_id = other_customer_id
        test_client.customer_token = core.make_token(1, "customer")
        test_client.other_customer_token = core.make_token(2, "customer")
        test_client.admin_token = core.make_token(3, "admin")
        yield test_client
    engine.dispose()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_upload_is_encrypted_private_and_customer_scoped(client, tmp_path):
    response = client.post("/api/v1/kyc/documents", headers=auth(client.customer_token),
                           data={"document_type": "pan"},
                           files={"file": ("card.png", png_bytes(), "image/png")})
    assert response.status_code == 201
    uploaded = response.json()
    assert uploaded["status"] == "Pending Review"
    assert "OCR is disabled" in uploaded["customer_message"]

    with main.Session() as db:
        document = db.get(KycDocument, uploaded["id"])
        encrypted_path = document.stored_path
        assert b"\x89PNG" not in open(encrypted_path, "rb").read()
    own_file = client.get(f"/api/v1/kyc/documents/{uploaded['id']}/file", headers=auth(client.customer_token))
    assert own_file.status_code == 200 and own_file.content == png_bytes()
    assert own_file.headers["content-type"] == "application/octet-stream"
    assert client.get(f"/api/v1/kyc/documents/{uploaded['id']}/file",
                      headers=auth(client.other_customer_token)).status_code == 404
    preview = client.get(f"/api/v1/kyc/documents/{uploaded['id']}/preview", headers=auth(client.customer_token))
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"


def test_customer_cannot_access_reviewer_queue_and_reviewer_must_decide(client):
    assert client.get("/api/v1/kyc/applications", headers=auth(client.customer_token)).status_code == 403
    assert client.get("/api/v1/kyc/applications", headers=auth(client.admin_token)).status_code == 200
    assert client.get("/api/v1/kyc/me", headers=auth(client.customer_token)).status_code == 200
    upload = client.post("/api/v1/kyc/documents", headers=auth(client.customer_token),
                         data={"document_type": "pan"},
                         files={"file": ("card.png", png_bytes(), "image/png")})
    doc_id = upload.json()["id"]
    assert client.get(f"/api/v1/kyc/documents/{doc_id}/review",
                      headers=auth(client.customer_token)).status_code == 403
    reviewer = client.get(f"/api/v1/kyc/documents/{doc_id}/review", headers=auth(client.admin_token))
    assert reviewer.status_code == 200 and "review_history" in reviewer.json()


def test_demo_customer_registration_creates_a_scoped_profile(client, monkeypatch):
    monkeypatch.setattr(core, "DEMO", True)
    response = client.post("/api/v1/auth/register", json={
        "email": "new-customer@test.invalid", "name": "New Synthetic Customer",
        "password": "StrongDemo@1234", "country": "IN",
    })
    assert response.status_code == 201
    token = response.json()["token"]
    dashboard = client.get("/api/v1/kyc/me", headers=auth(token))
    assert dashboard.status_code == 200
    assert dashboard.json()["profile"]["name"] == "New Synthetic Customer"
    assert dashboard.json()["profile"]["kyc_status"] == "pending"
    duplicate = client.post("/api/v1/auth/register", json={
        "email": "new-customer@test.invalid", "name": "New Synthetic Customer",
        "password": "StrongDemo@1234", "country": "IN",
    })
    assert duplicate.status_code == 409
    monkeypatch.setattr(core, "DEMO", False)
    disabled = client.post("/api/v1/auth/register", json={
        "email": "another@test.invalid", "name": "Another Customer",
        "password": "StrongDemo@1234", "country": "IN",
    })
    assert disabled.status_code == 404


def test_production_startup_rejects_demo_configuration(monkeypatch):
    monkeypatch.setattr(core, "ENV", "production")
    monkeypatch.setattr(core, "DEMO", True)
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        main.startup()


def test_upload_validation_rejects_extension_mime_mismatch_and_password_pdf():
    with pytest.raises(kyc.KycError, match="extension"):
        kyc.validate_upload("document.jpg", pdf_bytes())
    with pytest.raises(kyc.KycError, match="extension"):
        kyc.validate_upload("document.pdf", png_bytes())
    with pytest.raises(kyc.KycError, match="PDF, JPG"):
        kyc.validate_upload("document.txt", b"text")


def test_upload_rejects_corrupt_and_oversized_content(monkeypatch):
    monkeypatch.setattr(core, "MAX_MB", 1)
    with pytest.raises(kyc.KycError, match="damaged"):
        kyc.validate_upload("broken.png", b"\x89PNG\r\n\x1a\nbroken")
    with pytest.raises(kyc.KycError, match="upload limit"):
        kyc.validate_upload("large.png", b"x" * (1024 * 1024 + 1))


def test_unconfigured_ocr_is_an_explicit_failure(monkeypatch):
    monkeypatch.setattr(core, "KYC_OCR_ENABLED", True)
    monkeypatch.setattr(core, "HF_TOKEN", "")
    monkeypatch.setattr(core, "HF_OCR_MODEL", "")
    with pytest.raises(kyc.KycError, match="not configured"):
        kyc.extract_text(png_bytes(), "image/png")


def test_ocr_retries_loading_responses_and_returns_extracted_text(monkeypatch):
    monkeypatch.setattr(core, "KYC_OCR_ENABLED", True)
    monkeypatch.setattr(core, "HF_TOKEN", "test-token")
    monkeypatch.setattr(core, "HF_OCR_MODEL", "test/ocr-model")
    monkeypatch.setattr(kyc.time, "sleep", lambda _: None)
    responses = [SimpleNamespace(status_code=503), SimpleNamespace(status_code=503),
                 SimpleNamespace(status_code=200, json=lambda: [{"generated_text": "Name: Synthetic Person"}])]
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(kyc.httpx, "post", post)
    assert "Synthetic Person" in kyc._ocr_image(png_bytes())
    assert len(calls) == 3 and calls[0].endswith("/test/ocr-model")


def test_extraction_validation_expiry_and_masking(monkeypatch):
    monkeypatch.setattr(core, "KYC_ENCRYPTION_KEY", "unit-test-secret")
    fields = kyc.extract_fields(
        "Name: Synthetic Person\nPAN: ABCDE1234F\nDate of Birth: 01/01/1990\nExpiry Date: 01/01/2000",
        "pan",
    )
    fields["expiry_date"] = {"value": "01/01/2000", "normalized": "01/01/2000"}
    checks = kyc.validate_fields(fields, "pan")
    assert checks["required_fields_present"]
    assert {"check": "PAN format", "passed": True} in checks["format_checks"]
    assert any(item.get("expired") is True for item in checks["format_checks"])
    assert fields["date_of_birth"]["normalized"] == "1990-01-01"
    doc = KycDocument(extracted_fields=kyc.encrypt_text(json.dumps({
        "identity_number": {"value": "1234 5678 9012", "normalized": "123456789012"}
    })))
    assert kyc.customer_fields(doc)["identity_number"]["value"] == "********9012"


def test_manual_human_review_does_not_claim_issuer_verification(client):
    upload = client.post("/api/v1/kyc/documents", headers=auth(client.customer_token),
                         data={"document_type": "aadhaar"},
                         files={"file": ("card.png", png_bytes(), "image/png")})
    document_id = upload.json()["id"]
    decision = client.post(f"/api/v1/kyc/documents/{document_id}/decision", headers=auth(client.admin_token),
                           json={"status": "Verified", "reason": "Reviewed synthetic test document"})
    assert decision.status_code == 200
    dashboard = client.get("/api/v1/kyc/me", headers=auth(client.customer_token)).json()
    assert dashboard["progress"]["completion_percent"] == 50
    assert dashboard["profile"]["kyc_status"] == "pending"


def test_resubmission_requires_safe_customer_facing_message(client):
    upload = client.post("/api/v1/kyc/documents", headers=auth(client.customer_token),
                         data={"document_type": "pan"},
                         files={"file": ("card.png", png_bytes(), "image/png")})
    document_id = upload.json()["id"]
    response = client.post(f"/api/v1/kyc/documents/{document_id}/decision", headers=auth(client.admin_token),
                           json={"status": "Resubmission Required", "reason": "Internal confidential note"})
    assert response.status_code == 422
    assert "Internal confidential note" not in response.text


def test_reviewer_corrections_are_audited_and_extraction_can_be_retried(client):
    upload = client.post("/api/v1/kyc/documents", headers=auth(client.customer_token),
                         data={"document_type": "pan"},
                         files={"file": ("card.png", png_bytes(), "image/png")})
    document_id = upload.json()["id"]
    correction = client.post(f"/api/v1/kyc/documents/{document_id}/corrections", headers=auth(client.admin_token),
                             json={"fields": {"name": "Corrected Synthetic Name"}, "reason": "Manual comparison"})
    assert correction.status_code == 200
    assert correction.json()["fields"]["name"]["source"] == "reviewer"
    assert correction.json()["review_history"][0]["action"] == "correction"
    retry = client.post(f"/api/v1/kyc/documents/{document_id}/retry-ocr", headers=auth(client.customer_token))
    assert retry.status_code == 200
    assert retry.json()["status"] == "Verification Failed"
