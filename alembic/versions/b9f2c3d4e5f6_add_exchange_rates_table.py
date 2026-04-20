"""add exchange_rates table

Revision ID: b9f2c3d4e5f6
Revises: a8f1b2c3d4e5
Create Date: 2026-04-15 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9f2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'a8f1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='exchange_rates'"
    ))
    if result.fetchone() is None:
        op.create_table(
            'exchange_rates',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('from_currency', sa.VARCHAR(), nullable=False),
            sa.Column('to_currency', sa.VARCHAR(), nullable=False),
            sa.Column('rate', sa.Float(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_exchange_rates_pair', 'exchange_rates',
            ['from_currency', 'to_currency'], unique=True,
        )


def downgrade() -> None:
    op.drop_index('ix_exchange_rates_pair', table_name='exchange_rates')
    op.drop_table('exchange_rates')
