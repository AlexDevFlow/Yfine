"""add savings fund flags + goals tables + linked_goal_id on whims

Revision ID: a3b4c5d6e7f8
Revises: f1a2b3c4d5e6
Create Date: 2026-04-20 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(conn, table: str, col: str) -> bool:
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def _table_exists(conn, table: str) -> bool:
    insp = sa.inspect(conn)
    return table in insp.get_table_names()


def _idx_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=:n"
        ),
        {"n": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # --- sources: is_savings_fund, hidden_from_sources ---
    if not _col_exists(conn, "sources", "is_savings_fund"):
        op.add_column(
            "sources",
            sa.Column("is_savings_fund", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _col_exists(conn, "sources", "hidden_from_sources"):
        op.add_column(
            "sources",
            sa.Column("hidden_from_sources", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # --- movements: is_savings_contribution ---
    if not _col_exists(conn, "movements", "is_savings_contribution"):
        op.add_column(
            "movements",
            sa.Column("is_savings_contribution", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # --- goals ---
    if not _table_exists(conn, "goals"):
        op.create_table(
            "goals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("target_amount", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=True),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column("linked_whim_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["linked_whim_id"], ["whims.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _idx_exists(conn, "ix_goals_source_id"):
        op.create_index("ix_goals_source_id", "goals", ["source_id"])
    if not _idx_exists(conn, "ix_goals_status"):
        op.create_index("ix_goals_status", "goals", ["status"])

    # --- goal_allocations ---
    if not _table_exists(conn, "goal_allocations"):
        op.create_table(
            "goal_allocations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("goal_id", sa.Integer(), nullable=False),
            sa.Column("movement_id", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["movement_id"], ["movements.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _idx_exists(conn, "ix_goal_allocations_goal_id"):
        op.create_index("ix_goal_allocations_goal_id", "goal_allocations", ["goal_id"])
    if not _idx_exists(conn, "ix_goal_allocations_movement_id"):
        op.create_index("ix_goal_allocations_movement_id", "goal_allocations", ["movement_id"])

    # --- whims: linked_goal_id (SQLite cannot add a FK column, add as plain int) ---
    if not _col_exists(conn, "whims", "linked_goal_id"):
        op.add_column("whims", sa.Column("linked_goal_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_goal_allocations_movement_id", table_name="goal_allocations")
    op.drop_index("ix_goal_allocations_goal_id", table_name="goal_allocations")
    op.drop_table("goal_allocations")
    op.drop_index("ix_goals_status", table_name="goals")
    op.drop_index("ix_goals_source_id", table_name="goals")
    op.drop_table("goals")
    op.drop_column("whims", "linked_goal_id")
    op.drop_column("movements", "is_savings_contribution")
    op.drop_column("sources", "hidden_from_sources")
    op.drop_column("sources", "is_savings_fund")
