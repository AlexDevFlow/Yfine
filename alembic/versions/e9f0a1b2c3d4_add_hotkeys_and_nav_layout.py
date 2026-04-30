"""add hotkeys + nav layout to settings

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-04-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('settings', sa.Column('hotkeys_enabled', sa.BOOLEAN(), nullable=False, server_default=sa.text('1')))
    op.add_column('settings', sa.Column('hotkeys_json', sa.VARCHAR(), nullable=False, server_default='{}'))
    op.add_column('settings', sa.Column('nav_layout_json', sa.VARCHAR(), nullable=False, server_default='[]'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('settings', 'nav_layout_json')
    op.drop_column('settings', 'hotkeys_json')
    op.drop_column('settings', 'hotkeys_enabled')
