import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

if os.environ.get("PRO_TRADER_SIM_DB"):
    # Override, used by the test suite so it never touches the real database.
    DB_PATH = Path(os.environ["PRO_TRADER_SIM_DB"])
elif getattr(sys, "frozen", False):
    # Packaged app: its folder may be read-only, and every start is a fresh week anyway, so use a
    # per-process file in the temp folder (two running copies can't wipe each other). run.py deletes it on exit.
    DB_PATH = Path(tempfile.gettempdir()) / f"pro_trader_sim_{os.getpid()}.db"
else:
    # Anchored to this file so the app works no matter which directory it's launched from.
    DB_PATH = Path(__file__).resolve().parent / "simulator.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
