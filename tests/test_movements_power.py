"""Tests for movements power UX: bulk ops, filters, make-recurring,
cross-currency transfers, and quick-add templates."""
from datetime import date, timedelta

import pytest
from sqlmodel import select

from models.movement import Movement, MovementTag
from models.recurring import RecurringItem
from models.source import Source
from models.tag import Tag
from schemas.movement import TransferCreate, TransferUpdate
from services.movements import (
    bulk_delete,
    bulk_set_exclude,
    bulk_set_source,
    bulk_set_tags,
    count_movements,
    create_transfer,
    list_movements,
    make_recurring_from_movement,
    update_transfer,
)
from services.settings import get_settings


# ── helpers ──────────────────────────────────────────────────────

def _src(session, name="Bank", currency="EUR"):
    s = Source(name=name, currency=currency)
    session.add(s); session.commit(); session.refresh(s)
    return s


def _tag(session, name):
    t = Tag(name=name)
    session.add(t); session.commit(); session.refresh(t)
    return t


def _mov(session, source_id, amount, direction="out", note=None, when=None,
         tag_ids=None, exclude=False):
    m = Movement(source_id=source_id, amount=amount, direction=direction,
                 date=when or date.today(), note=note, exclude_from_stats=exclude)
    session.add(m); session.commit(); session.refresh(m)
    for tid in (tag_ids or []):
        session.add(MovementTag(movement_id=m.id, tag_id=tid))
    session.commit()
    return m


def _tags_of(session, mid):
    return {l.tag_id for l in session.exec(select(MovementTag).where(MovementTag.movement_id == mid)).all()}


# ── Bulk operations ──────────────────────────────────────────────

class TestBulkDelete:
    def test_delete_many(self, session):
        s = _src(session)
        ids = [_mov(session, s.id, 10).id for _ in range(3)]
        res = bulk_delete(session, ids)
        assert res["affected"] == 3 and res["skipped"] == []
        assert session.exec(select(Movement)).all() == []

    def test_transfer_pair_skipped(self, session):
        a, b = _src(session, "A"), _src(session, "B")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=a.id, to_source_id=b.id, amount=50, date=date.today()))
        res = bulk_delete(session, [out_m.id, in_m.id])
        # Deleting the out-leg cascades the in-leg; the second id is already gone
        # (consumed by the cascade), so it counts once and isn't a real "skip".
        assert res["affected"] == 1
        assert res["skipped"] == []
        assert session.exec(select(Movement)).all() == []


class TestBulkTags:
    def test_add_remove_replace(self, session):
        s = _src(session)
        t1, t2, t3 = _tag(session, "a"), _tag(session, "b"), _tag(session, "c")
        m = _mov(session, s.id, 10, tag_ids=[t1.id])
        bulk_set_tags(session, [m.id], [t2.id], "add")
        assert _tags_of(session, m.id) == {t1.id, t2.id}
        bulk_set_tags(session, [m.id], [t1.id], "remove")
        assert _tags_of(session, m.id) == {t2.id}
        bulk_set_tags(session, [m.id], [t3.id], "replace")
        assert _tags_of(session, m.id) == {t3.id}

    def test_unknown_tag_rejected(self, session):
        from fastapi import HTTPException
        s = _src(session); m = _mov(session, s.id, 10)
        with pytest.raises(HTTPException) as exc:
            bulk_set_tags(session, [m.id], [9999], "add")
        assert exc.value.status_code == 422

    def test_mirrors_to_transfer_partner(self, session):
        a, b = _src(session, "A"), _src(session, "B")
        t = _tag(session, "x")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=a.id, to_source_id=b.id, amount=50, date=date.today()))
        bulk_set_tags(session, [out_m.id], [t.id], "add")
        assert _tags_of(session, out_m.id) == {t.id}
        assert _tags_of(session, in_m.id) == {t.id}  # partner kept in sync


class TestBulkSourceExclude:
    def test_set_source(self, session):
        s1, s2 = _src(session, "S1"), _src(session, "S2")
        m = _mov(session, s1.id, 10)
        res = bulk_set_source(session, [m.id], s2.id)
        assert res["affected"] == 1
        assert session.get(Movement, m.id).source_id == s2.id

    def test_set_source_skips_transfer(self, session):
        a, b, c = _src(session, "A"), _src(session, "B"), _src(session, "C")
        out_m, _ = create_transfer(session, TransferCreate(
            from_source_id=a.id, to_source_id=b.id, amount=50, date=date.today()))
        res = bulk_set_source(session, [out_m.id], c.id)
        assert res["affected"] == 0 and res["skipped"] == [out_m.id]

    def test_set_exclude_mirrors_partner(self, session):
        a, b = _src(session, "A"), _src(session, "B")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=a.id, to_source_id=b.id, amount=50, date=date.today()))
        bulk_set_exclude(session, [out_m.id], True)
        assert session.get(Movement, out_m.id).exclude_from_stats is True
        assert session.get(Movement, in_m.id).exclude_from_stats is True


# ── Filters ──────────────────────────────────────────────────────

class TestFilters:
    def test_note_search(self, session):
        s = _src(session)
        _mov(session, s.id, 10, note="Rent April")
        _mov(session, s.id, 20, note="Groceries")
        _mov(session, s.id, 30, note=None)
        res = list_movements(session, q="rent")
        assert len(res) == 1 and res[0].note == "Rent April"

    def test_tag_match_and_vs_or(self, session):
        s = _src(session)
        t1, t2 = _tag(session, "a"), _tag(session, "b")
        both = _mov(session, s.id, 10, tag_ids=[t1.id, t2.id])
        _mov(session, s.id, 20, tag_ids=[t1.id])
        or_res = list_movements(session, tag_ids=[t1.id, t2.id], tag_match="or")
        and_res = list_movements(session, tag_ids=[t1.id, t2.id], tag_match="and")
        assert len(or_res) == 2
        assert len(and_res) == 1 and and_res[0].id == both.id
        # count must agree with the AND result set
        assert count_movements(session, tag_ids=[t1.id, t2.id], tag_match="and") == 1


# ── Make recurring ───────────────────────────────────────────────

class TestMakeRecurring:
    def test_from_movement_with_source(self, session):
        s = _src(session, currency="USD")
        m = _mov(session, s.id, 42.5, direction="out", note="Netflix")
        item = make_recurring_from_movement(session, m.id, "monthly", "auto")
        assert isinstance(item, RecurringItem)
        assert item.currency == "USD"
        assert item.amount == 42.5
        assert item.direction == "out"
        assert item.source_id == s.id
        assert item.frequency == "monthly" and item.apply_mode == "auto"
        assert item.name == "Netflix"
        # start_date anchors the cadence to the source movement, but the first
        # due date is rolled into the future so 'auto' never back-fills the past.
        assert item.start_date == m.date
        assert item.next_due_date > date.today()

    def test_external_uses_base_currency(self, session):
        settings = get_settings(session)
        settings.base_currency = "EUR"
        session.add(settings); session.commit()
        m = _mov(session, None, 10, note="Cash")
        item = make_recurring_from_movement(session, m.id, "weekly", "confirm")
        assert item.currency == "EUR"

    def test_external_no_currency_422(self, session):
        from fastapi import HTTPException
        settings = get_settings(session)
        settings.base_currency = None
        session.add(settings); session.commit()
        m = _mov(session, None, 10)
        with pytest.raises(HTTPException) as exc:
            make_recurring_from_movement(session, m.id, "monthly", "confirm")
        assert exc.value.status_code == 422

    def test_transfer_rejected(self, session):
        from fastapi import HTTPException
        a, b = _src(session, "A"), _src(session, "B")
        out_m, _ = create_transfer(session, TransferCreate(
            from_source_id=a.id, to_source_id=b.id, amount=50, date=date.today()))
        with pytest.raises(HTTPException) as exc:
            make_recurring_from_movement(session, out_m.id, "monthly", "confirm")
        assert exc.value.status_code == 400


# ── Cross-currency transfers ─────────────────────────────────────

class TestCrossCurrencyTransfer:
    def test_legs_differ_with_to_amount(self, session):
        eur, usd = _src(session, "EUR", "EUR"), _src(session, "USD", "USD")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=eur.id, to_source_id=usd.id, amount=100, to_amount=108, date=date.today()))
        assert out_m.amount == 100 and in_m.amount == 108

    def test_same_currency_stays_1to1(self, session):
        a, b = _src(session, "A", "EUR"), _src(session, "B", "EUR")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=a.id, to_source_id=b.id, amount=100, date=date.today()))
        assert out_m.amount == 100 and in_m.amount == 100

    def test_update_does_not_clobber_converted_leg(self, session):
        eur, usd = _src(session, "EUR", "EUR"), _src(session, "USD", "USD")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=eur.id, to_source_id=usd.id, amount=100, to_amount=108, date=date.today()))
        # Edit only the sent amount; the converted in-leg must stay untouched.
        update_transfer(session, out_m.id, TransferUpdate(amount=200))
        assert session.get(Movement, out_m.id).amount == 200
        assert session.get(Movement, in_m.id).amount == 108
        # Providing to_amount updates the in-leg.
        update_transfer(session, out_m.id, TransferUpdate(to_amount=216))
        assert session.get(Movement, in_m.id).amount == 216

    def test_update_same_currency_mirrors_amount(self, session):
        a, b = _src(session, "A", "EUR"), _src(session, "B", "EUR")
        out_m, in_m = create_transfer(session, TransferCreate(
            from_source_id=a.id, to_source_id=b.id, amount=100, date=date.today()))
        update_transfer(session, out_m.id, TransferUpdate(amount=150))
        assert session.get(Movement, out_m.id).amount == 150
        assert session.get(Movement, in_m.id).amount == 150


# ── Templates / saved views service ──────────────────────────────

class TestTemplatesService:
    def test_prunes_stale_ids(self, session):
        from services import movement_templates as mt
        s = _src(session)
        t = _tag(session, "valid")
        settings = get_settings(session)
        settings.movement_templates_json = (
            '[{"name":"ok","direction":"out","source_id":%d,"amount":12,"tag_ids":[%d,9999]},'
            '{"name":"stale","direction":"in","source_id":8888,"tag_ids":[]},'
            '{"no_name":true}]' % (s.id, t.id)
        )
        session.add(settings); session.commit()
        items = mt.list_templates(session)
        assert len(items) == 2  # the one without a name is dropped
        ok = items[0]
        assert ok["source_id"] == s.id and ok["tag_ids"] == [t.id]  # 9999 pruned
        stale = items[1]
        assert stale["source_id"] is None  # 8888 pruned to external

    def test_saved_views_parse(self, session):
        from services import movement_templates as mt
        settings = get_settings(session)
        settings.saved_views_json = '[{"name":"This year","params":{"date_from":"2026-01-01"}},{"bad":1}]'
        session.add(settings); session.commit()
        views = mt.list_saved_views(session)
        assert len(views) == 1 and views[0]["name"] == "This year"
