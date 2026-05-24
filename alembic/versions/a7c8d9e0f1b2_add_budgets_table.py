"""add budgets table

Revision ID: a7c8d9e0f1b2
Revises: f2b3c4d5e6a7
Create Date: 2026-05-22 16:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "a7c8d9e0f1b2"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # init_db runs SQLModel.create_all() before migrations, so on most installs
    # this table already exists — guard the create so the upgrade stays a no-op
    # instead of failing with "table already exists".
    insp = sa.inspect(op.get_bind())
    if insp.has_table("budgets"):
        return
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("period", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("direction", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("rollover", sa.Boolean(), nullable=False),
        sa.Column("alert_threshold_pct", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("last_alert_period", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("last_alert_level", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budgets_tag_id", "budgets", ["tag_id"], unique=False)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("budgets"):
        return
    op.drop_index("ix_budgets_tag_id", table_name="budgets")
    op.drop_table("budgets")
