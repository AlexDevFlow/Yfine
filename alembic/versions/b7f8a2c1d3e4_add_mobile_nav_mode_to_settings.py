"""add mobile_nav_mode to settings

Revision ID: b7f8a2c1d3e4
Revises: 3928ebb81706
Create Date: 2026-04-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7f8a2c1d3e4'
down_revision: Union[str, Sequence[str], None] = '3928ebb81706'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('settings', sa.Column('mobile_nav_mode', sa.VARCHAR(), nullable=False, server_default='sidebar'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('settings', 'mobile_nav_mode')
