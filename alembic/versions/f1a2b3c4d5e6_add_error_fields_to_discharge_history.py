"""add error_type and failure_reason to discharge_history

Revision ID: f1a2b3c4d5e6
Revises: 898469434cce
Create Date: 2026-03-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '898469434cce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('discharge_history', sa.Column('error_type', sa.String(30), nullable=True))
    op.add_column('discharge_history', sa.Column('failure_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('discharge_history', 'failure_reason')
    op.drop_column('discharge_history', 'error_type')
