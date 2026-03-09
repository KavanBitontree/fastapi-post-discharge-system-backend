"""add upload session table

Revision ID: 3df3b06127eb
Revises: d5d5fa02a75d
Create Date: 2026-03-09 16:49:16.908469

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3df3b06127eb'
down_revision: Union[str, Sequence[str], None] = 'd5d5fa02a75d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
