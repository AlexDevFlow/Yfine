"""add portfolios, holdings and portfolio price settings

Revision ID: c4d5e6f7a8b9
Revises: b9f2c3d4e5f6
Create Date: 2026-04-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b9f2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Settings columns ---
    op.add_column('settings', sa.Column('portfolio_prices_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('settings', sa.Column('portfolio_prices_prompted', sa.Boolean(), nullable=False, server_default=sa.false()))

    # --- Portfolios ---
    op.create_table(
        'portfolios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='mixed'),
        sa.Column('base_currency', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='EUR'),
        sa.Column('note', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- Holdings ---
    op.create_table(
        'holdings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=False),
        sa.Column('asset_class', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('symbol', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('avg_cost', sa.Float(), nullable=False, server_default='0'),
        sa.Column('currency', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='EUR'),
        sa.Column('last_price', sa.Float(), nullable=True),
        sa.Column('last_price_at', sa.DateTime(), nullable=True),
        sa.Column('manual_price', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('note', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_holdings_portfolio_id', 'holdings', ['portfolio_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_holdings_portfolio_id', table_name='holdings')
    op.drop_table('holdings')
    op.drop_table('portfolios')
    op.drop_column('settings', 'portfolio_prices_prompted')
    op.drop_column('settings', 'portfolio_prices_enabled')
