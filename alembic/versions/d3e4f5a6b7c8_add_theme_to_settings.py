"""add_theme_to_settings

Revision ID: d3e4f5a6b7c8
Revises: 0f323efeee70
Create Date: 2026-04-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = ('0f323efeee70', 'c3d4e5f6g7h8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('settings', sa.Column('theme', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='light'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('settings', 'theme')
