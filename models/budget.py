from datetime import date, datetime
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class Budget(SQLModel, table=True):
    """A recurring spending (or income) limit attached to a tag.

    A budget is single-currency: its "actual" is the sum of movements that carry
    ``tag_id``, match ``direction``, fall in the period, and whose source is in
    ``currency`` (transfers and exclude-from-stats movements never count). The
    rule renews automatically every ``period``; nothing is materialised per
    period — actuals and rollover are computed live from the movements so the
    figures self-heal when past movements are edited.

    When ``rollover`` is on, the signed remainder of each period (surplus *and*
    overspend) carries into the next, giving envelope-style behaviour.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        Index("ix_budgets_tag_id", "tag_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tag_id: int = Field(foreign_key="tags.id")
    amount: float
    currency: str  # ISO 4217
    period: str = Field(default="monthly")  # weekly | monthly | quarterly | yearly
    direction: str = Field(default="out")   # "out" (spending cap) | "in" (income target)
    rollover: bool = Field(default=False)
    alert_threshold_pct: int = Field(default=80)  # 0 disables threshold/overspend alerts
    active: bool = Field(default=True)
    # Anchors the rollover walk; periods are otherwise calendar-aligned.
    start_date: date = Field(default_factory=date.today)
    # Alert idempotency: the period key (e.g. "2026-05") last alerted on, and the
    # highest level reached then (threshold pct or 100), so we fire once per band.
    last_alert_period: Optional[str] = Field(default=None)
    last_alert_level: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
