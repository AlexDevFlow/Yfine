"""link portfolios to sources (source_id NOT NULL, RESTRICT)

Revision ID: d5e6f7a8b9c1
Revises: c4d5e6f7a8b9
Create Date: 2026-04-19 19:00:00.000000

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c1'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: portfolios.source_id NOT NULL with ondelete=RESTRICT.

    Strategy for non-destructive migration:
      1. Add source_id as NULLABLE (no FK yet) so we can populate existing rows.
      2. Backfill orphan portfolios (source_id IS NULL):
           - assign to the first existing source (lowest id), OR
           - if no sources exist, create a fallback "Investments" source.
      3. Alter the column to NOT NULL and add the FK with ondelete='RESTRICT'.
    """
    # Step 1: add column (nullable, no FK yet)
    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_id', sa.Integer(), nullable=True))

    # Step 2: backfill
    conn = op.get_bind()
    orphan_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM portfolios WHERE source_id IS NULL")
    ).scalar() or 0

    if orphan_count > 0:
        first_source = conn.execute(
            sa.text("SELECT id FROM sources ORDER BY id ASC LIMIT 1")
        ).first()

        if first_source is None:
            now = datetime.utcnow().isoformat()
            conn.execute(
                sa.text(
                    "INSERT INTO sources "
                    "(name, currency, starting_balance, exclude_from_stats, "
                    "created_at, updated_at) "
                    "VALUES (:name, :currency, 0, 0, :created, :updated)"
                ),
                {
                    "name": "Investments",
                    "currency": "EUR",
                    "created": now,
                    "updated": now,
                },
            )
            fallback_id = conn.execute(
                sa.text("SELECT id FROM sources ORDER BY id DESC LIMIT 1")
            ).scalar()
        else:
            fallback_id = first_source[0]

        conn.execute(
            sa.text(
                "UPDATE portfolios SET source_id = :sid WHERE source_id IS NULL"
            ),
            {"sid": fallback_id},
        )

    # Step 3: make NOT NULL and attach FK with RESTRICT
    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.alter_column('source_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            'fk_portfolios_source_id',
            'sources',
            ['source_id'],
            ['id'],
            ondelete='RESTRICT',
        )


def downgrade() -> None:
    """Downgrade schema: make source_id nullable again and drop the FK."""
    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.drop_constraint('fk_portfolios_source_id', type_='foreignkey')
        batch_op.alter_column('source_id', existing_type=sa.Integer(), nullable=True)
        batch_op.drop_column('source_id')
