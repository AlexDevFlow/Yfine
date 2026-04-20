"""add performance indices

Revision ID: a8f1b2c3d4e5
Revises: 77fb7438de78
Create Date: 2026-04-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a8f1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = '77fb7438de78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(conn, index_name: str) -> bool:
    """Check if an index already exists in SQLite."""
    result = conn.execute(
        __import__("sqlalchemy").text(
            f"SELECT name FROM sqlite_master WHERE type='index' AND name='{index_name}'"
        )
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # movements table indices
    if not _index_exists(conn, "ix_movements_source_id"):
        op.create_index("ix_movements_source_id", "movements", ["source_id"])
    if not _index_exists(conn, "ix_movements_date"):
        op.create_index("ix_movements_date", "movements", ["date"])
    if not _index_exists(conn, "ix_movements_transfer_pair_id"):
        op.create_index("ix_movements_transfer_pair_id", "movements", ["transfer_pair_id"])
    if not _index_exists(conn, "ix_movements_source_id_direction"):
        op.create_index("ix_movements_source_id_direction", "movements", ["source_id", "direction"])

    # recurring_items table indices
    if not _index_exists(conn, "ix_recurring_items_next_due_date"):
        op.create_index("ix_recurring_items_next_due_date", "recurring_items", ["next_due_date"])
    if not _index_exists(conn, "ix_recurring_items_source_id"):
        op.create_index("ix_recurring_items_source_id", "recurring_items", ["source_id"])

    # notifications table indices
    if not _index_exists(conn, "ix_notifications_is_read"):
        op.create_index("ix_notifications_is_read", "notifications", ["is_read"])
    if not _index_exists(conn, "ix_notifications_created_at"):
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    if not _index_exists(conn, "ix_notifications_related_entity_type"):
        op.create_index("ix_notifications_related_entity_type", "notifications", ["related_entity", "type"])


def downgrade() -> None:
    op.drop_index("ix_notifications_related_entity_type", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_is_read", table_name="notifications")
    op.drop_index("ix_recurring_items_source_id", table_name="recurring_items")
    op.drop_index("ix_recurring_items_next_due_date", table_name="recurring_items")
    op.drop_index("ix_movements_source_id_direction", table_name="movements")
    op.drop_index("ix_movements_transfer_pair_id", table_name="movements")
    op.drop_index("ix_movements_date", table_name="movements")
    op.drop_index("ix_movements_source_id", table_name="movements")
