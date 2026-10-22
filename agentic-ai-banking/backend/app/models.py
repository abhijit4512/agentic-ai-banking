from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Column, Integer, String, Numeric, DateTime, JSON, Text, Index
from .db import Base

def now():
    """Naive UTC timestamp (DB columns are naive). Replaces the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def row(o, skip=()):
    out = {}
    for c in o.__table__.columns:
        if c.name in skip: continue
        v = getattr(o, c.name)
        out[c.name] = float(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, datetime) else v
    return out

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True); email = Column(String, unique=True, index=True)
    name = Column(String); role = Column(String); pw = Column(String); customer_id = Column(Integer, nullable=True)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True); name = Column(String); type = Column(String, default="individual")
    country = Column(String); occupation = Column(String); source_of_funds = Column(String)
    account = Column(String, index=True); kyc_status = Column(String, default="pending"); kyc_note = Column(Text)
    created = Column(DateTime, default=now)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True); customer_id = Column(Integer, index=True); account = Column(String, index=True)
    amount = Column(Numeric(14, 2)); currency = Column(String, default="USD"); ts = Column(DateTime, index=True)
    type = Column(String); merchant = Column(String); channel = Column(String); country = Column(String)
    status = Column(String, default="completed"); score = Column(Integer, default=0)
    severity = Column(String, default="none"); reasons = Column(JSON, default=list)

class Alert(Base):
    __tablename__ = "fraud_alerts"
    id = Column(Integer, primary_key=True); txn_id = Column(String, index=True); customer_id = Column(Integer)
    severity = Column(String); score = Column(Integer); reasons = Column(JSON); status = Column(String, default="open")
    assignee = Column(String); notes = Column(JSON, default=list); action_state = Column(String)
    created = Column(DateTime, default=now)

class Case(Base):
    __tablename__ = "compliance_cases"
    id = Column(Integer, primary_key=True); customer_id = Column(Integer, index=True); kind = Column(String)
    matches = Column(JSON, default=list); status = Column(String, default="open"); notes = Column(JSON, default=list)
    sar_drafts = Column(JSON, default=list); created = Column(DateTime, default=now)

class Dispute(Base):
    __tablename__ = "disputes"
    id = Column(Integer, primary_key=True); customer_id = Column(Integer, index=True); txn_id = Column(String)
    reason = Column(Text); status = Column(String, default="draft"); created = Column(DateTime, default=now)

class Loan(Base):
    __tablename__ = "loan_applications"
    id = Column(Integer, primary_key=True); customer_id = Column(Integer, index=True); applicant = Column(String)
    loan_type = Column(String); amount = Column(Numeric(14, 2)); term_months = Column(Integer); rate = Column(Numeric(6, 3))
    income = Column(Numeric(14, 2)); debt = Column(Numeric(14, 2)); employment = Column(String)
    status = Column(String, default="submitted"); docs = Column(JSON, default=list)
    assessment = Column(JSON); decision_note = Column(Text); created = Column(DateTime, default=now)

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True); name = Column(String); owner_id = Column(Integer); path = Column(String)
    status = Column(String, default="processing"); pages = Column(Integer, default=0); note = Column(Text)
    created = Column(DateTime, default=now)

class KycDocument(Base):
    __tablename__ = "kyc_documents"
    id = Column(Integer, primary_key=True); customer_id = Column(Integer, index=True); uploaded_by = Column(Integer)
    document_type = Column(String, index=True); original_filename = Column(String); stored_path = Column(String)
    mime_type = Column(String); file_size = Column(Integer); sha256 = Column(String, index=True)
    status = Column(String, default="Uploaded", index=True); extracted_text = Column(Text)
    extracted_fields = Column(Text); review_history = Column(Text)
    validation = Column(JSON, default=dict); customer_message = Column(Text); reviewer_notes = Column(Text)
    supersedes_id = Column(Integer); page_count = Column(Integer, default=1); created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now); reviewed_by = Column(String); reviewed_at = Column(DateTime)

class Chunk(Base):
    __tablename__ = "document_chunks"
    id = Column(Integer, primary_key=True); doc_id = Column(Integer, index=True); page = Column(Integer); text = Column(Text)

class Tbl(Base):
    __tablename__ = "extracted_tables"
    id = Column(Integer, primary_key=True); doc_id = Column(Integer, index=True); page = Column(Integer); rows = Column(JSON)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True); ts = Column(DateTime, default=now, index=True)
    actor = Column(String); action = Column(String); detail = Column(Text)
    # Hash chain: hash = sha256(prev_hash | ts | actor | action | detail). Rows are append-only (see audit.py).
    prev_hash = Column(String); hash = Column(String, index=True)

class RevokedToken(Base):
    """Server-side deny-list so /auth/logout really invalidates a JWT (by jti) until it would expire."""
    __tablename__ = "revoked_tokens"
    jti = Column(String, primary_key=True); expires = Column(Integer, index=True); revoked_at = Column(DateTime, default=now)

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    id = Column(Integer, primary_key=True); key = Column(String, index=True); actor = Column(String, index=True)
    txn_id = Column(String); created = Column(DateTime, default=now)
