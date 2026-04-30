"""add ui_scale to settings

Revision ID: d8e9f0a1b2c3
Revises: c5d6e7f8a9b0
Create Date: 2026-04-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('settings', sa.Column('ui_scale', sa.VARCHAR(), nullable=False, server_default='normal'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('settings', 'ui_scale')
