"""add is_discharged flag to patients

Revision ID: f4e5d6c7b8a9
Revises: 0cdbeb06f6e5
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa

revision = "f4e5d6c7b8a9"
down_revision = "0cdbeb06f6e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "is_discharged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("patients", "is_discharged", server_default=None)


def downgrade() -> None:
    op.drop_column("patients", "is_discharged")
