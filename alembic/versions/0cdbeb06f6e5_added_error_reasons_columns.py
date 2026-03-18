"""reconcile error reason fields without dropping columns

Revision ID: 0cdbeb06f6e5
Revises: 919d580d2e20
Create Date: 2026-03-13 15:09:59.673502

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0cdbeb06f6e5'
down_revision: Union[str, Sequence[str], None] = '919d580d2e20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Intentionally no-op. Keep existing error columns for current backend models.
    pass


def downgrade() -> None:
    """Downgrade schema."""
    # Intentionally no-op.
    pass
