"""add periodic yield/interest fields to sources

Revision ID: f2b3c4d5e6a7
Revises: e9f0a1b2c3d4
Create Date: 2026-05-22 16:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2b3c4d5e6a7"
down_revision: Union[str, Sequence[str], None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _col_exists(conn, "sources", "yield_rate"):
        op.add_column(
            "sources",
            sa.Column("yield_rate", sa.Float(), nullable=False, server_default="0"),
        )
    if not _col_exists(conn, "sources", "yield_period_months"):
        op.add_column(
            "sources",
            sa.Column("yield_period_months", sa.Integer(), nullable=False, server_default="12"),
        )
    if not _col_exists(conn, "sources", "yield_next_date"):
        op.add_column("sources", sa.Column("yield_next_date", sa.Date(), nullable=True))
    if not _col_exists(conn, "sources", "yield_last_date"):
        op.add_column("sources", sa.Column("yield_last_date", sa.Date(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    for col in ("yield_last_date", "yield_next_date", "yield_period_months", "yield_rate"):
        if _col_exists(conn, "sources", col):
            with op.batch_alter_table("sources") as batch_op:
                batch_op.drop_column(col)
