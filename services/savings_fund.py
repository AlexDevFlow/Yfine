"""Savings fund helpers.

A "savings fund" is a regular Source with `is_savings_fund=true`. Every
currency the user deposits gets exactly one fund (auto-created the first time
it's needed). The fund can be shown or hidden in /sources via the
`hidden_from_sources` flag.
"""
from sqlmodel import Session, select

from i18n import _
from models.source import Source


def _default_fund_name(currency: str) -> str:
    # The name is stored plain so exports/imports survive without translation
    # machinery, but we try to localize at creation time.
    return f"{_('savings_fund')} ({currency})"


def list_funds(session: Session) -> list[Source]:
    return list(
        session.exec(
            select(Source).where(Source.is_savings_fund == True)  # noqa: E712
        ).all()
    )


def get_fund_for_currency(session: Session, currency: str) -> Source | None:
    return session.exec(
        select(Source).where(
            Source.is_savings_fund == True,  # noqa: E712
            Source.currency == currency,
        )
    ).first()


def ensure_fund_for_currency(session: Session, currency: str) -> Source:
    """Return the fund for this currency, creating one on first call."""
    fund = get_fund_for_currency(session, currency)
    if fund:
        return fund
    fund = Source(
        name=_default_fund_name(currency),
        currency=currency,
        starting_balance=0.0,
        is_savings_fund=True,
        hidden_from_sources=False,
    )
    session.add(fund)
    session.commit()
    session.refresh(fund)
    return fund


def is_savings_fund(source: Source) -> bool:
    return bool(source and source.is_savings_fund)
