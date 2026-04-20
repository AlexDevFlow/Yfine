"""Tests for commit.py and undo.py — non-destructive batch insert + rollback."""
from datetime import date, datetime

from sqlmodel import select

from models.movement import Movement
from models.source import Source
from services.importers.base import ParsedMovement
from services.importers.commit import commit
from services.importers.undo import delete_batch, make_undo_token, verify_undo_token


def _src(session, currency="EUR"):
    s = Source(name="Test", currency=currency, starting_balance=0)
    session.add(s); session.commit(); session.refresh(s)
    return s


def test_commit_creates_selected_movements(session):
    s = _src(session)
    parsed = [
        ParsedMovement(date=date(2024, 1, 1), amount=10.0, direction="in", note="A", raw_hash="1"),
        ParsedMovement(date=date(2024, 1, 2), amount=5.0, direction="out", note="B", raw_hash="2"),
        ParsedMovement(date=date(2024, 1, 3), amount=20.0, direction="in", note="C", raw_hash="3"),
    ]
    result = commit(session, parsed, s.id, [True, False, True])
    assert result.imported == 2
    assert result.skipped == 1
    movs = session.exec(select(Movement).where(Movement.source_id == s.id)).all()
    assert len(movs) == 2
    notes = {m.note for m in movs}
    assert notes == {"A", "C"}


def test_commit_exclude_from_stats(session):
    s = _src(session)
    parsed = [ParsedMovement(date=date(2024, 1, 1), amount=10.0, direction="in", note="X", raw_hash="1")]
    commit(session, parsed, s.id, [True], exclude_from_stats=True)
    m = session.exec(select(Movement).where(Movement.source_id == s.id)).one()
    assert m.exclude_from_stats is True


def test_commit_mismatched_flags_raises(session):
    s = _src(session)
    parsed = [ParsedMovement(date=date(2024, 1, 1), amount=1, direction="in", note=None, raw_hash="1")]
    import pytest
    with pytest.raises(ValueError):
        commit(session, parsed, s.id, [True, False])


def test_undo_roundtrip(session, monkeypatch):
    monkeypatch.setattr("services.importers.undo.get_session_secret", lambda: "test-secret-key")

    s = _src(session)
    before = datetime.utcnow()
    parsed = [
        ParsedMovement(date=date(2024, 1, 1), amount=10.0, direction="in", note="A", raw_hash="1"),
        ParsedMovement(date=date(2024, 1, 2), amount=5.0, direction="out", note="B", raw_hash="2"),
    ]
    commit(session, parsed, s.id, [True, True])
    after = datetime.utcnow()

    token = make_undo_token(s.id, before, after)
    assert verify_undo_token(token) is not None

    n = delete_batch(session, token)
    assert n == 2
    remaining = session.exec(select(Movement).where(Movement.source_id == s.id)).all()
    assert remaining == []


def test_undo_invalid_token(session, monkeypatch):
    monkeypatch.setattr("services.importers.undo.get_session_secret", lambda: "test-secret-key")
    assert delete_batch(session, "nonsense-token") is None
    assert verify_undo_token("nonsense-token") is None
