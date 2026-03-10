"""add created_at to discharge_history

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'discharge_history',
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('discharge_history', 'created_at')
