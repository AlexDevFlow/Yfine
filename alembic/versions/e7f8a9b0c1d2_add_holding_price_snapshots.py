"""add holding_price_snapshots table

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c1
Create Date: 2026-04-19 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'holding_price_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('holding_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['holding_id'], ['holdings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('holding_id', 'date', name='uq_holding_snapshot_date'),
    )
    op.create_index(
        'ix_holding_price_snapshots_holding_date',
        'holding_price_snapshots',
        ['holding_id', 'date'],
    )


def downgrade() -> None:
    op.drop_index('ix_holding_price_snapshots_holding_date', table_name='holding_price_snapshots')
    op.drop_table('holding_price_snapshots')
