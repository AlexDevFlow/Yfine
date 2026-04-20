from fastapi import APIRouter, Depends
from sqlmodel import Session

from database import get_session
from schemas.tag import TagCreate, TagRead, TagUpdate
from services import tags as tag_service

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagRead])
def list_tags(skip: int = 0, limit: int = 50, session: Session = Depends(get_session)):
    return tag_service.list_tags(session, skip, limit)


@router.post("", response_model=TagRead, status_code=201)
def create_tag(data: TagCreate, session: Session = Depends(get_session)):
    return tag_service.create_tag(session, data)


@router.put("/{tag_id}", response_model=TagRead)
def update_tag(tag_id: int, data: TagUpdate, session: Session = Depends(get_session)):
    return tag_service.update_tag(session, tag_id, data)


@router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: int, session: Session = Depends(get_session)):
    tag_service.delete_tag(session, tag_id)
