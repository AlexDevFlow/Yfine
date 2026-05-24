"""add saved_views_json and movement_templates_json to settings

Revision ID: b3c4d5e6f7a8
Revises: a7c8d9e0f1b2
Create Date: 2026-05-22 17:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a7c8d9e0f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _col_exists(conn, "settings", "saved_views_json"):
        op.add_column(
            "settings",
            sa.Column("saved_views_json", sa.VARCHAR(), nullable=False, server_default="[]"),
        )
    if not _col_exists(conn, "settings", "movement_templates_json"):
        op.add_column(
            "settings",
            sa.Column("movement_templates_json", sa.VARCHAR(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    for col in ("movement_templates_json", "saved_views_json"):
        if _col_exists(conn, "settings", col):
            with op.batch_alter_table("settings") as batch_op:
                batch_op.drop_column(col)
