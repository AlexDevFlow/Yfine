from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from models.movement import MovementTag
from models.tag import Tag
from schemas.tag import TagCreate, TagUpdate


def list_tags(session: Session, skip: int = 0, limit: int = 50) -> list[Tag]:
    return list(session.exec(select(Tag).offset(skip).limit(limit)).all())


def get_tag(session: Session, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


def create_tag(session: Session, data: TagCreate) -> Tag:
    tag = Tag(**data.model_dump())
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag


def update_tag(session: Session, tag_id: int, data: TagUpdate) -> Tag:
    tag = get_tag(session, tag_id)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tag, key, value)
    tag.updated_at = datetime.utcnow()
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag


def delete_tag(session: Session, tag_id: int) -> None:
    from services.budgets import delete_budgets_for_tag

    tag = get_tag(session, tag_id)
    # Remove all movement-tag links for this tag
    links = session.exec(
        select(MovementTag).where(MovementTag.tag_id == tag_id)
    ).all()
    for link in links:
        session.delete(link)
    # Drop any budgets that targeted this tag (SQLite FK is on, but cascade
    # the app-level invariant explicitly so the rule never outlives its tag).
    delete_budgets_for_tag(session, tag_id)
    session.delete(tag)
    session.commit()
