import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from . import core
os.makedirs("data", exist_ok=True)
engine = create_engine(core.DATABASE_URL, connect_args={"check_same_thread": False} if core.DATABASE_URL.startswith("sqlite") else {})
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()
