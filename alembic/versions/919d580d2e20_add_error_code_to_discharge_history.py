"""add error_code to discharge_history

Revision ID: 919d580d2e20
Revises: 51570389a0e0
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

revision = "919d580d2e20"
down_revision = "51570389a0e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discharge_history",
        sa.Column("error_code", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discharge_history", "error_code")
