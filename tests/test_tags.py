"""Tests for tags service — CRUD, cascade delete, movement links."""
from datetime import date

import pytest
from sqlmodel import select

from models.movement import Movement, MovementTag
from models.source import Source
from models.tag import Tag
from schemas.tag import TagCreate, TagUpdate
from services.tags import create_tag, delete_tag, get_tag, list_tags, update_tag


# ── helpers ──────────────────────────────────────────────────────

def _src(session):
    s = Source(name="Bank", currency="EUR", starting_balance=0)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _movement_with_tag(session, source_id, tag_id):
    m = Movement(source_id=source_id, amount=10, direction="in", date=date.today())
    session.add(m)
    session.flush()
    session.add(MovementTag(movement_id=m.id, tag_id=tag_id))
    session.commit()
    session.refresh(m)
    return m


# ── CRUD ─────────────────────────────────────────────────────────

class TestTagCRUD:
    def test_create_tag(self, session):
        t = create_tag(session, TagCreate(name="Groceries"))
        assert t.id is not None
        assert t.name == "Groceries"
        assert t.color is None

    def test_create_tag_with_color(self, session):
        t = create_tag(session, TagCreate(name="Urgent", color="#ff0000"))
        assert t.color == "#ff0000"

    def test_list_tags_empty(self, session):
        assert list_tags(session) == []

    def test_list_tags(self, session):
        create_tag(session, TagCreate(name="A"))
        create_tag(session, TagCreate(name="B"))
        create_tag(session, TagCreate(name="C"))
        assert len(list_tags(session)) == 3

    def test_list_tags_pagination(self, session):
        for i in range(10):
            create_tag(session, TagCreate(name=f"T{i}"))
        assert len(list_tags(session, skip=0, limit=5)) == 5
        assert len(list_tags(session, skip=8, limit=5)) == 2

    def test_get_tag(self, session):
        t = create_tag(session, TagCreate(name="Found"))
        assert get_tag(session, t.id).name == "Found"

    def test_get_tag_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_tag(session, 9999)
        assert exc.value.status_code == 404

    def test_update_tag_name(self, session):
        t = create_tag(session, TagCreate(name="Old"))
        updated = update_tag(session, t.id, TagUpdate(name="New"))
        assert updated.name == "New"

    def test_update_tag_color(self, session):
        t = create_tag(session, TagCreate(name="Colored"))
        updated = update_tag(session, t.id, TagUpdate(color="#00ff00"))
        assert updated.color == "#00ff00"

    def test_update_tag_partial(self, session):
        t = create_tag(session, TagCreate(name="Stable", color="#aaa"))
        updated = update_tag(session, t.id, TagUpdate(color="#bbb"))
        assert updated.name == "Stable"  # unchanged
        assert updated.color == "#bbb"


# ── Delete & Cascade ─────────────────────────────────────────────

class TestTagDelete:
    def test_delete_tag(self, session):
        t = create_tag(session, TagCreate(name="ToDelete"))
        delete_tag(session, t.id)
        assert session.get(Tag, t.id) is None

    def test_delete_tag_cleans_movement_links(self, session):
        s = _src(session)
        t = create_tag(session, TagCreate(name="Linked"))
        m = _movement_with_tag(session, s.id, t.id)

        # Verify link exists
        links = session.exec(select(MovementTag).where(MovementTag.tag_id == t.id)).all()
        assert len(links) == 1

        delete_tag(session, t.id)

        # Tag gone
        assert session.get(Tag, t.id) is None
        # Link gone
        links = session.exec(select(MovementTag).where(MovementTag.tag_id == t.id)).all()
        assert links == []
        # Movement still exists
        assert session.get(Movement, m.id) is not None

    def test_delete_tag_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            delete_tag(session, 9999)

    def test_delete_tag_with_multiple_movements(self, session):
        s = _src(session)
        t = create_tag(session, TagCreate(name="Multi"))
        _movement_with_tag(session, s.id, t.id)
        _movement_with_tag(session, s.id, t.id)
        _movement_with_tag(session, s.id, t.id)

        links_before = session.exec(select(MovementTag).where(MovementTag.tag_id == t.id)).all()
        assert len(links_before) == 3

        delete_tag(session, t.id)

        links_after = session.exec(select(MovementTag).where(MovementTag.tag_id == t.id)).all()
        assert links_after == []


# ── Tag card → movements filter (template regression) ────────────

class TestTagCardLinksFilteredMovements:
    """The tags page builds a card per tag with `data-href` pointing at the
    Movements page pre-filtered by that tag. The Movements router accepts
    `tag_ids` (plural, list-typed); a singular `tag_id` is silently ignored
    and the user lands on an unfiltered list. This test pins the correct
    query-param name so that bug doesn't come back.
    """

    TEMPLATE_PATH = "templates/tags/index.html"

    def test_card_uses_tag_ids_query_param(self):
        with open(self.TEMPLATE_PATH) as f:
            html = f.read()
        assert 'data-href="/movements?tag_ids=' in html, (
            "tag card must link with `tag_ids=` (plural) — `tag_id=` is silently dropped"
        )
        assert 'data-href="/movements?tag_id=' not in html

    def test_movements_router_accepts_tag_ids(self):
        """Sanity: the route handler signature still accepts `tag_ids`. If
        someone renames it to `tag_id` (singular), the template fix above
        becomes useless — flag both halves of the contract."""
        from inspect import signature
        from routers.pages import movements_index
        params = signature(movements_index).parameters
        assert "tag_ids" in params
        assert "tag_id" not in params
