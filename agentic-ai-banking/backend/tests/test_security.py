"""Security, authorization, audit-chain and fraud-rule tests."""
import time
from datetime import datetime, timedelta
from decimal import Decimal

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import core, kyc, main, rules
from app import models as M
from app.db import Base

PASSWORD = "Demo@12345"
PW_HASH = core.hash_pw(PASSWORD)  # hashed once: PBKDF2 is intentionally slow
ROLES = ("customer", "other", "admin", "analyst", "underwriter")


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'sec.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db:
        c1 = M.Customer(name="Synthetic Person", type="individual", country="IN", occupation="T", source_of_funds="S", account="TEST-1")
        c2 = M.Customer(name="Other Person", type="individual", country="IN", occupation="T", source_of_funds="S", account="TEST-2")
        db.add_all([c1, c2])
        db.flush()
        db.add_all([
            M.User(email="customer@test.invalid", name="Customer", role="customer", pw=PW_HASH, customer_id=c1.id),
            M.User(email="other@test.invalid", name="Other", role="customer", pw=PW_HASH, customer_id=c2.id),
            M.User(email="admin@test.invalid", name="Admin", role="admin", pw=PW_HASH, customer_id=None),
            M.User(email="analyst@test.invalid", name="Analyst", role="analyst", pw=PW_HASH, customer_id=None),
            M.User(email="underwriter@test.invalid", name="Underwriter", role="underwriter", pw=PW_HASH, customer_id=None),
        ])
        db.commit()
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "Session", testing_session)
    monkeypatch.setattr(core, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(core, "KYC_ENCRYPTION_KEY", "test-key-used-only-in-tests")
    main._hits.clear()
    main._lock.clear()
    with TestClient(main.app) as c:
        c.tokens = {role: core.make_token(i + 1, "customer" if role in ("customer", "other") else role) for i, role in enumerate(ROLES)}
        yield c
    engine.dispose()


# ---------------------------------------------------------------- tokens
def test_jwt_has_standard_claims_and_rejects_tampering():
    token = core.make_token(7, "admin")
    payload = core.read_token(token)
    assert payload["u"] == 7 and payload["iss"] == core.JWT_ISSUER and payload["aud"] == core.JWT_AUDIENCE and payload["jti"]
    assert core.read_token(token + "x") is None
    assert core.read_token(core.make_token(7, "admin", ttl=-5)) is None  # expired


def test_jwt_rejects_forged_and_incomplete_tokens():
    forged = jwt.encode({"u": 1, "r": "admin", "typ": "access", "iss": core.JWT_ISSUER, "aud": core.JWT_AUDIENCE,
                         "iat": 1, "exp": int(time.time()) + 99, "jti": "x"}, "some-other-secret-some-other-secret!", algorithm="HS256")
    assert core.read_token(forged) is None
    unsigned = jwt.encode({"u": 1, "exp": int(time.time()) + 99}, core.SECRET, algorithm="HS256")
    assert core.read_token(unsigned) is None  # missing aud/iss/jti


def test_media_and_access_tokens_are_not_interchangeable():
    media = core.make_token(1, "customer", ttl=60, typ="media")
    assert core.read_token(media) is None and core.read_token(media, typ="media")["u"] == 1
    assert core.read_token(core.make_token(1, "customer"), typ="media") is None


def test_kyc_key_rotation_keeps_old_data_readable(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(core, "KYC_ENCRYPTION_KEY", old)
    sealed = kyc.encrypt_text("sensitive")
    monkeypatch.setattr(core, "KYC_ENCRYPTION_KEY", f"{new},{old}")
    assert kyc.decrypt_text(sealed) == "sensitive"
    monkeypatch.setattr(core, "KYC_ENCRYPTION_KEY", new)
    with pytest.raises(RuntimeError):
        kyc.decrypt_text(sealed)


# ---------------------------------------------------------------- authentication
@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/transactions", "/api/v1/fraud/alerts", "/api/v1/audit-logs",
                                  "/api/v1/kyc/me", "/api/v1/dashboard/summary", "/api/v1/documents"])
def test_protected_routes_reject_anonymous_requests(client, path):
    assert client.get(path).status_code == 401


def test_logout_revokes_the_token_server_side(client):
    token = core.make_token(3, "admin")
    assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=auth(token)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401


def test_query_string_tokens_only_work_as_media_tokens_on_page_images(client):
    media = client.post("/api/v1/auth/media-token", headers=auth(client.tokens["admin"])).json()["token"]
    assert client.get("/api/v1/auth/me", params={"token": media}).status_code == 401           # wrong route
    assert client.get("/api/v1/auth/me", headers=auth(media)).status_code == 401               # media is not an access token
    assert client.get("/api/v1/documents/999/pages/1", params={"token": client.tokens["admin"]}).status_code == 401  # access token in URL
    assert client.get("/api/v1/documents/999/pages/1", params={"token": media}).status_code == 404  # authenticated, doc missing


def test_login_returns_token_and_locks_out_after_repeated_failures(client):
    ok = client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": PASSWORD})
    assert ok.status_code == 200 and core.read_token(ok.json()["token"])["r"] == "admin"
    for _ in range(core.LOGIN_MAX_FAILURES):
        assert client.post("/api/v1/auth/login", json={"email": "analyst@test.invalid", "password": "wrong"}).status_code == 401
    locked = client.post("/api/v1/auth/login", json={"email": "analyst@test.invalid", "password": PASSWORD})
    assert locked.status_code == 429


# ---------------------------------------------------------------- authorization matrix
STAFF = {"admin", "analyst", "underwriter"}
MATRIX = [
    ("GET", "/api/v1/audit-logs", None, {"admin", "analyst"}),
    ("GET", "/api/v1/audit-logs/verify", None, {"admin"}),
    ("GET", "/api/v1/fraud/alerts", None, STAFF),
    ("GET", "/api/v1/dashboard/summary", None, STAFF),
    ("GET", "/api/v1/notifications", None, STAFF),
    ("GET", "/api/v1/kyc/applications", None, {"admin", "analyst"}),
    ("GET", "/api/v1/kyc/stats", None, {"admin", "analyst"}),
    ("GET", "/api/v1/compliance/cases", None, {"admin", "analyst"}),
    ("POST", "/api/v1/compliance/screen", {"name": "Test Person"}, {"admin", "analyst"}),
    ("POST", "/api/v1/transactions/simulate", None, STAFF),
    ("POST", "/api/v1/documents/1/reprocess", None, {"admin", "analyst"}),
    ("POST", "/api/v1/loans/applications/1/decision", {"decision": "approved", "note": "reviewed ok"}, {"admin", "underwriter"}),
]


@pytest.mark.parametrize("method,path,body,allowed", MATRIX)
@pytest.mark.parametrize("role", ROLES)
def test_role_endpoint_authorization_matrix(client, role, method, path, body, allowed):
    effective_role = "customer" if role in ("customer", "other") else role
    response = client.request(method, path, headers=auth(client.tokens[role]), json=body)
    if effective_role in allowed:
        assert response.status_code not in (401, 403), (role, path, response.status_code)
    else:
        assert response.status_code == 403, (role, path, response.status_code)


# ---------------------------------------------------------------- audit log
def test_audit_chain_verifies_and_detects_tampering(client):
    client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": "bad"})
    client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": "bad"})
    client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": PASSWORD})
    report = client.get("/api/v1/audit-logs/verify", headers=auth(client.tokens["admin"])).json()
    assert report["ok"] is True and report["checked"] >= 3

    with main.Session() as db:  # raw SQL bypasses the ORM guard, simulating someone editing the database
        db.execute(text("UPDATE audit_logs SET detail = 'tampered' WHERE id = 1"))
        db.commit()
    report = client.get("/api/v1/audit-logs/verify", headers=auth(client.tokens["admin"])).json()
    assert report["ok"] is False and report["first_bad_id"] == 1


def test_audit_rows_cannot_be_updated_or_deleted_through_the_orm(client):
    client.post("/api/v1/auth/login", json={"email": "admin@test.invalid", "password": "bad"})
    with main.Session() as db:
        entry = db.query(M.AuditLog).first()
        entry.detail = "edited"
        with pytest.raises(RuntimeError):
            db.commit()
    with main.Session() as db:
        entry = db.query(M.AuditLog).first()
        db.delete(entry)
        with pytest.raises(RuntimeError):
            db.commit()


# ---------------------------------------------------------------- business rules in the API
def test_hold_release_requires_an_existing_hold_and_two_person_approval(client):
    with main.Session() as db:
        db.add(M.Alert(txn_id="TXN-000001", customer_id=1, severity="high", score=60, reasons=[]))
        db.commit()
    url, admin, analyst = "/api/v1/fraud/alerts/1/action", client.tokens["admin"], client.tokens["analyst"]
    assert client.post(url, headers=auth(analyst), json={"action": "release", "reason": "x"}).status_code == 409
    assert client.post(url, headers=auth(analyst), json={"action": "request_hold", "reason": "suspicious"}).json()["action_state"] == "pending_approval"
    assert client.post(url, headers=auth(analyst), json={"action": "approve_hold", "reason": "x"}).status_code == 403
    assert client.post(url, headers=auth(admin), json={"action": "approve_hold", "reason": "ok"}).json()["action_state"] == "hold_simulated"
    assert client.post(url, headers=auth(admin), json={"action": "release", "reason": "cleared"}).json()["action_state"] == "released"


def test_staff_support_chat_must_name_a_customer(client):
    assert client.post("/api/v1/support/chat", headers=auth(client.tokens["admin"]), json={"message": "hello"}).status_code == 422
    assert client.post("/api/v1/support/chat", headers=auth(client.tokens["admin"]), json={"message": "hello", "customer_id": 1}).status_code == 200
    assert client.post("/api/v1/support/chat", headers=auth(client.tokens["customer"]), json={"message": "hello"}).status_code == 200


def test_transaction_events_are_idempotent(client):
    body = {"account": "TEST-1", "amount": 125.5, "merchant": "Shop"}
    headers = {**auth(client.tokens["admin"]), "Idempotency-Key": "retry-1"}
    first = client.post("/api/v1/transactions/events", headers=headers, json=body)
    second = client.post("/api/v1/transactions/events", headers=headers, json=body)
    assert first.status_code == 201 and second.json()["id"] == first.json()["id"]
    assert len(client.get("/api/v1/transactions", headers=auth(client.tokens["admin"])).json()) == 1


def test_ready_endpoint_reports_dependencies(client):
    response = client.get("/api/v1/ready")
    assert response.status_code == 200 and response.json()["checks"] == {"database": "ok", "storage": "ok"}


# ---------------------------------------------------------------- fraud rules (no HTTP layer)
@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


T0 = datetime(2026, 1, 1, 12, 0)


def ingest(db, amount, ts=T0, account="ACC-A", country="IN", status="completed"):
    return rules.ingest_txn(db, ts=ts, customer_id=1, account=account, amount=Decimal(str(amount)), type="card",
                            merchant="m", channel="web", country=country, status=status)


def codes(txn):
    return {r["code"] for r in txn.reasons}


def test_transaction_ids_increment(db):
    assert [ingest(db, 10, ts=T0 + timedelta(hours=i)).id for i in range(3)] == ["TXN-000001", "TXN-000002", "TXN-000003"]


def test_high_amount_boundary(db):
    assert "HIGH_AMOUNT" not in codes(ingest(db, "9999.99", account="A"))
    assert "HIGH_AMOUNT" in codes(ingest(db, "10000.00", account="B"))


def test_velocity_fires_on_the_fifth_transaction_in_ten_minutes(db):
    results = [ingest(db, 10, ts=T0 + timedelta(minutes=i)) for i in range(5)]
    assert [("VELOCITY" in codes(t)) for t in results] == [False, False, False, False, True]


def test_repeated_failures_fire_on_the_third_failure(db):
    results = [ingest(db, 10, ts=T0 + timedelta(minutes=i), status="failed") for i in range(3)]
    assert [("REPEATED_FAILURES" in codes(t)) for t in results] == [False, False, True]


def test_amount_spike_boundary_is_strictly_greater_than_five_times_average(db):
    for i in range(5):
        ingest(db, 100, ts=T0 + timedelta(hours=i), account="S1")
        ingest(db, 100, ts=T0 + timedelta(hours=i), account="S2")
    assert "AMOUNT_SPIKE" not in codes(ingest(db, 500, ts=T0 + timedelta(hours=9), account="S1"))
    assert "AMOUNT_SPIKE" in codes(ingest(db, 501, ts=T0 + timedelta(hours=9), account="S2"))


def test_structuring_pattern_after_three_just_under_threshold(db):
    results = [ingest(db, amt, ts=T0 + timedelta(days=i)) for i, amt in enumerate(["9000", "9500", "9999.99"])]
    assert [("STRUCTURING_PATTERN" in codes(t)) for t in results] == [False, False, True]


def test_new_geography_only_after_history_exists(db):
    first = ingest(db, 10, country="IN")
    second = ingest(db, 10, ts=T0 + timedelta(hours=1), country="BR")
    assert "NEW_GEOGRAPHY" not in codes(first) and "NEW_GEOGRAPHY" in codes(second)


def test_flagging_creates_an_alert_with_reasons(db):
    ingest(db, 10, country="IN")
    big = ingest(db, 20000, ts=T0 + timedelta(hours=1), country="BR")  # HIGH_AMOUNT 35 + NEW_GEOGRAPHY 15 = 50
    assert big.score == 50 and big.severity == "medium" and big.status == "flagged"
    assert db.query(M.Alert).filter_by(txn_id=big.id).count() == 1
