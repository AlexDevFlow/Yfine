"""add last_fired_date and last_alert_date to recurring_items

Revision ID: c5d6e7f8a9b0
Revises: a3b4c5d6e7f8
Create Date: 2026-04-27 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _col_exists(conn, "recurring_items", "last_fired_date"):
        op.add_column(
            "recurring_items",
            sa.Column("last_fired_date", sa.Date(), nullable=True),
        )
    if not _col_exists(conn, "recurring_items", "last_alert_date"):
        op.add_column(
            "recurring_items",
            sa.Column("last_alert_date", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _col_exists(conn, "recurring_items", "last_alert_date"):
        with op.batch_alter_table("recurring_items") as batch_op:
            batch_op.drop_column("last_alert_date")
    if _col_exists(conn, "recurring_items", "last_fired_date"):
        with op.batch_alter_table("recurring_items") as batch_op:
            batch_op.drop_column("last_fired_date")
