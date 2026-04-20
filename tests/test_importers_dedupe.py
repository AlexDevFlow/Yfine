"""Tests for dedupe: hash determinism, whitespace/case insensitivity, window."""
from datetime import date

from models.movement import Movement
from models.source import Source
from services.importers.base import ParsedMovement
from services.importers.dedupe import find_existing_hashes, mark_duplicates, row_hash


def _src(session, currency="EUR"):
    s = Source(name="Test", currency=currency, starting_balance=0)
    session.add(s); session.commit(); session.refresh(s)
    return s


def test_row_hash_deterministic():
    h1 = row_hash(1, date(2024, 1, 1), 10.5, "in", "Salary")
    h2 = row_hash(1, date(2024, 1, 1), 10.5, "in", "Salary")
    assert h1 == h2


def test_row_hash_case_and_whitespace_insensitive_note():
    h1 = row_hash(1, date(2024, 1, 1), 10.0, "in", "  SALARY  ")
    h2 = row_hash(1, date(2024, 1, 1), 10.0, "in", "salary")
    assert h1 == h2


def test_row_hash_differs_on_amount():
    h1 = row_hash(1, date(2024, 1, 1), 10.0, "in", "x")
    h2 = row_hash(1, date(2024, 1, 1), 10.01, "in", "x")
    assert h1 != h2


def test_find_existing_hashes_matches(session):
    s = _src(session)
    m = Movement(source_id=s.id, amount=50.0, direction="in", date=date(2024, 2, 1), note="Rent")
    session.add(m); session.commit()

    parsed = [
        ParsedMovement(date=date(2024, 2, 1), amount=50.0, direction="in", note="Rent", raw_hash="a"),
        ParsedMovement(date=date(2024, 2, 2), amount=10.0, direction="out", note="Coffee", raw_hash="b"),
    ]
    hashes = find_existing_hashes(session, s.id, parsed)
    assert row_hash(s.id, date(2024, 2, 1), 50.0, "in", "Rent") in hashes


def test_mark_duplicates(session):
    s = _src(session)
    m = Movement(source_id=s.id, amount=12.0, direction="out", date=date(2024, 3, 1), note="Lunch")
    session.add(m); session.commit()

    parsed = [
        ParsedMovement(date=date(2024, 3, 1), amount=12.0, direction="out", note="Lunch", raw_hash="a"),
        ParsedMovement(date=date(2024, 3, 2), amount=5.0, direction="out", note="Coffee", raw_hash="b"),
        ParsedMovement(date=date(2024, 3, 2), amount=5.0, direction="out", note="Coffee", raw_hash="c"),  # same-batch dup
    ]
    flags = mark_duplicates(session, s.id, parsed)
    assert flags == [True, False, True]


def test_mark_duplicates_no_source_returns_all_false(session):
    parsed = [ParsedMovement(date=date(2024, 1, 1), amount=1, direction="in", note=None, raw_hash="x")]
    assert mark_duplicates(session, None, parsed) == [False]
