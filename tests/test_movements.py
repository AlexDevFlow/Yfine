"""Tests for movements service — CRUD, transfers, filters, tags, grouping."""
from datetime import date, timedelta

import pytest
from sqlmodel import select

from models.movement import Movement, MovementTag
from models.source import Source
from models.tag import Tag
from schemas.movement import MovementCreate, MovementUpdate, TransferCreate, TransferUpdate
from services.movements import (
    count_movements,
    create_movement,
    create_transfer,
    delete_movement,
    enrich_movements_with_sources,
    get_movement,
    get_movement_tags,
    group_movements_hierarchically,
    list_movements,
    toggle_exclude_from_stats,
    update_movement,
    update_transfer,
)


# ── helpers ──────────────────────────────────────────────────────

def _src(session, name="Bank", currency="EUR", balance=0.0):
    s = Source(name=name, currency=currency, starting_balance=balance)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _tag(session, name="Food", color=None):
    t = Tag(name=name, color=color)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


# ── CRUD ─────────────────────────────────────────────────────────

class TestMovementCRUD:
    def test_create_with_source(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=42.5, direction="in", date=date.today(),
        ))
        assert m.id is not None
        assert m.amount == 42.5
        assert m.source_id == s.id

    def test_create_external(self, session):
        m = create_movement(session, MovementCreate(
            amount=10, direction="out", date=date.today(),
        ))
        assert m.source_id is None

    def test_create_with_nonexistent_source_raises(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            create_movement(session, MovementCreate(
                source_id=9999, amount=10, direction="in", date=date.today(),
            ))
        assert exc.value.status_code == 404

    def test_get_movement(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=20, direction="out", date=date.today(),
        ))
        found = get_movement(session, m.id)
        assert found.amount == 20

    def test_get_movement_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            get_movement(session, 9999)

    def test_update_movement(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
        ))
        updated = update_movement(session, m.id, MovementUpdate(amount=99, note="Updated"))
        assert updated.amount == 99
        assert updated.note == "Updated"
        assert updated.direction == "in"  # unchanged

    def test_update_movement_change_source(self, session):
        s1 = _src(session, name="A")
        s2 = _src(session, name="B")
        m = create_movement(session, MovementCreate(
            source_id=s1.id, amount=10, direction="in", date=date.today(),
        ))
        updated = update_movement(session, m.id, MovementUpdate(source_id=s2.id))
        assert updated.source_id == s2.id

    def test_update_movement_invalid_source_raises(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
        ))
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            update_movement(session, m.id, MovementUpdate(source_id=9999))

    def test_delete_movement(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
        ))
        delete_movement(session, m.id)
        assert session.get(Movement, m.id) is None

    def test_delete_movement_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            delete_movement(session, 9999)


# ── Tags ─────────────────────────────────────────────────────────

class TestMovementTags:
    def test_create_with_tags(self, session):
        s = _src(session)
        t1 = _tag(session, "Food")
        t2 = _tag(session, "Lunch")
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=15, direction="out", date=date.today(),
            tag_ids=[t1.id, t2.id],
        ))
        tags = get_movement_tags(session, m.id)
        assert len(tags) == 2
        tag_names = {t.name for t in tags}
        assert tag_names == {"Food", "Lunch"}

    def test_update_replaces_tags(self, session):
        s = _src(session)
        t1 = _tag(session, "A")
        t2 = _tag(session, "B")
        t3 = _tag(session, "C")
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
            tag_ids=[t1.id, t2.id],
        ))
        update_movement(session, m.id, MovementUpdate(tag_ids=[t3.id]))
        tags = get_movement_tags(session, m.id)
        assert len(tags) == 1
        assert tags[0].name == "C"

    def test_delete_cleans_tag_links(self, session):
        s = _src(session)
        t = _tag(session, "X")
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
            tag_ids=[t.id],
        ))
        mid = m.id
        delete_movement(session, mid)
        links = session.exec(select(MovementTag).where(MovementTag.movement_id == mid)).all()
        assert links == []

    def test_get_tags_empty(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
        ))
        assert get_movement_tags(session, m.id) == []


# ── Transfers ────────────────────────────────────────────────────

class TestTransfers:
    def test_create_transfer(self, session):
        s1 = _src(session, name="From")
        s2 = _src(session, name="To")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=s1.id, to_source_id=s2.id,
            amount=200, date=date.today(), note="Transfer",
        ))
        assert out_m.direction == "out"
        assert out_m.source_id == s1.id
        assert in_m.direction == "in"
        assert in_m.source_id == s2.id
        assert out_m.transfer_pair_id == in_m.id
        assert in_m.transfer_pair_id == out_m.id
        assert out_m.amount == in_m.amount == 200

    def test_transfer_with_tags(self, session):
        s1 = _src(session, name="A")
        s2 = _src(session, name="B")
        t = _tag(session, "Transfer")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=s1.id, to_source_id=s2.id,
            amount=50, date=date.today(), tag_ids=[t.id],
        ))
        out_tags = get_movement_tags(session, out_m.id)
        in_tags = get_movement_tags(session, in_m.id)
        assert len(out_tags) == 1
        assert len(in_tags) == 1

    def test_transfer_nonexistent_from_source(self, session):
        s = _src(session)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            create_transfer(session, TransferCreate(
                from_source_id=9999, to_source_id=s.id,
                amount=10, date=date.today(),
            ))
        assert exc.value.status_code == 404

    def test_transfer_nonexistent_to_source(self, session):
        s = _src(session)
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            create_transfer(session, TransferCreate(
                from_source_id=s.id, to_source_id=9999,
                amount=10, date=date.today(),
            ))

    def test_transfer_same_source_rejected(self):
        with pytest.raises(ValueError):
            TransferCreate(
                from_source_id=1, to_source_id=1,
                amount=10, date=date.today(),
            )

    def test_delete_transfer_deletes_partner(self, session):
        s1 = _src(session, name="X")
        s2 = _src(session, name="Y")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=s1.id, to_source_id=s2.id,
            amount=100, date=date.today(),
        ))
        delete_movement(session, out_m.id)
        assert session.get(Movement, out_m.id) is None
        assert session.get(Movement, in_m.id) is None

    def test_update_transfer(self, session):
        s1 = _src(session, name="A")
        s2 = _src(session, name="B")
        s3 = _src(session, name="C")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=s1.id, to_source_id=s2.id,
            amount=100, date=date.today(),
        ))
        new_out, new_in = update_transfer(session, out_m.id, TransferUpdate(
            amount=200, to_source_id=s3.id,
        ))
        assert new_out.amount == 200
        assert new_in.amount == 200
        assert new_in.source_id == s3.id
        assert new_out.source_id == s1.id  # unchanged

    def test_update_non_transfer_raises(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
        ))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            update_transfer(session, m.id, TransferUpdate(amount=99))
        assert exc.value.status_code == 400


# ── Filters ──────────────────────────────────────────────────────

class TestMovementFilters:
    def test_filter_by_source(self, session):
        s1 = _src(session, name="A")
        s2 = _src(session, name="B")
        create_movement(session, MovementCreate(source_id=s1.id, amount=10, direction="in", date=date.today()))
        create_movement(session, MovementCreate(source_id=s2.id, amount=20, direction="out", date=date.today()))
        result = list_movements(session, source_id=s1.id)
        assert len(result) == 1
        assert result[0].source_id == s1.id

    def test_filter_by_direction(self, session):
        s = _src(session)
        create_movement(session, MovementCreate(source_id=s.id, amount=10, direction="in", date=date.today()))
        create_movement(session, MovementCreate(source_id=s.id, amount=20, direction="out", date=date.today()))
        result = list_movements(session, direction="out")
        assert len(result) == 1
        assert result[0].direction == "out"

    def test_filter_by_date_range(self, session):
        s = _src(session)
        today = date.today()
        create_movement(session, MovementCreate(source_id=s.id, amount=10, direction="in", date=today - timedelta(days=30)))
        create_movement(session, MovementCreate(source_id=s.id, amount=20, direction="in", date=today - timedelta(days=5)))
        create_movement(session, MovementCreate(source_id=s.id, amount=30, direction="in", date=today))
        result = list_movements(session, date_from=today - timedelta(days=7), date_to=today)
        assert len(result) == 2

    def test_filter_by_amount_range(self, session):
        s = _src(session)
        create_movement(session, MovementCreate(source_id=s.id, amount=5, direction="in", date=date.today()))
        create_movement(session, MovementCreate(source_id=s.id, amount=50, direction="in", date=date.today()))
        create_movement(session, MovementCreate(source_id=s.id, amount=500, direction="in", date=date.today()))
        result = list_movements(session, amount_min=10, amount_max=100)
        assert len(result) == 1
        assert result[0].amount == 50

    def test_filter_by_tag(self, session):
        s = _src(session)
        t = _tag(session, "Groceries")
        m1 = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="out", date=date.today(), tag_ids=[t.id],
        ))
        m2 = create_movement(session, MovementCreate(
            source_id=s.id, amount=20, direction="out", date=date.today(),
        ))
        result = list_movements(session, tag_ids=[t.id])
        assert len(result) == 1
        assert result[0].id == m1.id

    def test_filter_invalid_date_range(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            list_movements(session, date_from=date(2026, 12, 1), date_to=date(2026, 1, 1))
        assert exc.value.status_code == 422

    def test_filter_invalid_amount_range(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            list_movements(session, amount_min=100, amount_max=10)
        assert exc.value.status_code == 422

    def test_count_movements(self, session):
        s = _src(session)
        create_movement(session, MovementCreate(source_id=s.id, amount=10, direction="in", date=date.today()))
        create_movement(session, MovementCreate(source_id=s.id, amount=20, direction="out", date=date.today()))
        assert count_movements(session) == 2
        assert count_movements(session, direction="in") == 1

    def test_pagination(self, session):
        s = _src(session)
        for i in range(10):
            create_movement(session, MovementCreate(
                source_id=s.id, amount=i + 1, direction="in", date=date.today(),
            ))
        page1 = list_movements(session, skip=0, limit=3)
        page2 = list_movements(session, skip=3, limit=3)
        assert len(page1) == 3
        assert len(page2) == 3
        ids1 = {m.id for m in page1}
        ids2 = {m.id for m in page2}
        assert ids1.isdisjoint(ids2)

    def test_exclude_transfer_in(self, session):
        s1 = _src(session, name="A")
        s2 = _src(session, name="B")
        create_transfer(session, TransferCreate(
            from_source_id=s1.id, to_source_id=s2.id,
            amount=100, date=date.today(),
        ))
        create_movement(session, MovementCreate(
            source_id=s1.id, amount=50, direction="in", date=date.today(),
        ))
        # Without filter: 3 movements (out transfer, in transfer, regular in)
        all_mvs = list_movements(session)
        assert len(all_mvs) == 3
        # With filter: should exclude transfer "in" side
        filtered = list_movements(session, exclude_transfer_in=True)
        assert len(filtered) == 2


# ── Toggle Exclude ───────────────────────────────────────────────

class TestToggleExcludeMovement:
    def test_toggle(self, session):
        s = _src(session)
        m = create_movement(session, MovementCreate(
            source_id=s.id, amount=10, direction="in", date=date.today(),
        ))
        assert m.exclude_from_stats is False
        m = toggle_exclude_from_stats(session, m.id)
        assert m.exclude_from_stats is True
        m = toggle_exclude_from_stats(session, m.id)
        assert m.exclude_from_stats is False


# ── Grouping ─────────────────────────────────────────────────────

class TestMovementGrouping:
    def test_multi_year_grouping(self):
        movements = [
            {"date": date(2025, 12, 15), "amount": 100, "direction": "in", "transfer_pair_id": None},
            {"date": date(2026, 1, 10), "amount": 50, "direction": "out", "transfer_pair_id": None},
            {"date": date(2026, 3, 5), "amount": 200, "direction": "in", "transfer_pair_id": None},
        ]
        grouped = group_movements_hierarchically(movements)
        assert len(grouped) == 2
        years = [g["year"] for g in grouped]
        assert 2025 in years
        assert 2026 in years

    def test_transfers_excluded_from_totals(self):
        movements = [
            {"date": date(2026, 3, 1), "amount": 100, "direction": "in", "transfer_pair_id": 5},
            {"date": date(2026, 3, 1), "amount": 100, "direction": "out", "transfer_pair_id": 4},
            {"date": date(2026, 3, 1), "amount": 50, "direction": "in", "transfer_pair_id": None},
        ]
        grouped = group_movements_hierarchically(movements)
        assert grouped[0]["total_in"] == 50.0  # transfer in excluded
        assert grouped[0]["total_out"] == 0.0   # transfer out excluded

    def test_same_day_multiple_movements(self):
        d = date(2026, 5, 15)
        movements = [
            {"date": d, "amount": 10, "direction": "in", "transfer_pair_id": None},
            {"date": d, "amount": 20, "direction": "in", "transfer_pair_id": None},
            {"date": d, "amount": 5, "direction": "out", "transfer_pair_id": None},
        ]
        grouped = group_movements_hierarchically(movements)
        day = grouped[0]["months"][0]["days"][0]
        assert len(day["movements"]) == 3
        assert day["total_in"] == 30.0
        assert day["total_out"] == 5.0


# ── Enrichment ───────────────────────────────────────────────────

class TestEnrichment:
    def test_enrich_with_deleted_source(self, session):
        s = _src(session)
        m = Movement(source_id=s.id, amount=10, direction="in", date=date.today())
        session.add(m)
        session.commit()
        session.refresh(m)
        # Delete the source record directly to simulate a deleted source
        session.delete(s)
        session.commit()
        enriched = enrich_movements_with_sources(session, [m])
        # Should show as "deleted" since source_id is set but source is gone
        assert len(enriched) == 1

    def test_enrich_external_movement(self, session):
        m = Movement(source_id=None, amount=10, direction="in", date=date.today())
        session.add(m)
        session.commit()
        session.refresh(m)
        enriched = enrich_movements_with_sources(session, [m])
        assert len(enriched) == 1
        # source_name should be the i18n "external" string
        assert enriched[0]["source_name"] is not None
