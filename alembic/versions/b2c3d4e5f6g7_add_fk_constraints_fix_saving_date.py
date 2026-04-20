"""add FK constraints, cascade on movement_tag, fix saving date type

Revision ID: b2c3d4e5f6g7
Revises: 0f323efeee70
Create Date: 2026-03-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = '0f323efeee70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    SQLite requires batch mode (table recreation) for FK and type changes.
    Using recreate='always' to ensure constraints are applied.
    """
    # 1. Recreate movement_tag with CASCADE on both FKs
    with op.batch_alter_table('movement_tag', schema=None, recreate='always',
                              table_args=[
                                  sa.ForeignKeyConstraint(['movement_id'], ['movements.id'], ondelete='CASCADE'),
                                  sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
                              ]) as batch_op:
        pass  # table recreation applies the new constraints

    # 2. Add FK constraint on movements.transfer_pair_id
    with op.batch_alter_table('movements', schema=None, recreate='always') as batch_op:
        batch_op.create_foreign_key(
            'fk_movements_transfer_pair_id', 'movements', ['transfer_pair_id'], ['id'], ondelete='SET NULL'
        )

    # 3. Change savings.date from VARCHAR to DATE
    with op.batch_alter_table('savings', schema=None, recreate='always') as batch_op:
        batch_op.alter_column('date',
                              existing_type=sa.String(),
                              type_=sa.Date(),
                              existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('savings', schema=None, recreate='always') as batch_op:
        batch_op.alter_column('date',
                              existing_type=sa.Date(),
                              type_=sa.String(),
                              existing_nullable=False)

    with op.batch_alter_table('movements', schema=None, recreate='always') as batch_op:
        batch_op.drop_constraint('fk_movements_transfer_pair_id', type_='foreignkey')

    with op.batch_alter_table('movement_tag', schema=None, recreate='always',
                              table_args=[
                                  sa.ForeignKeyConstraint(['movement_id'], ['movements.id']),
                                  sa.ForeignKeyConstraint(['tag_id'], ['tags.id']),
                              ]) as batch_op:
        pass
