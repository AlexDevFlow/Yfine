"""Shared fixtures for Yfine tests.

Uses an in-memory SQLite database so tests don't touch the real DB.
"""
import os
import sys
import pytest
from sqlmodel import SQLModel, Session, create_engine

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Override DATA_DIR before any app imports to prevent touching real data
os.environ["YFINE_DATA_DIR"] = "/tmp/yfine-test-data"
os.makedirs("/tmp/yfine-test-data", exist_ok=True)


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine with all tables."""
    import models  # noqa: F401 — register all models
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    return test_engine


@pytest.fixture
def session(engine):
    """Yield a session for each test, rolled back after."""
    with Session(engine) as session:
        yield session
