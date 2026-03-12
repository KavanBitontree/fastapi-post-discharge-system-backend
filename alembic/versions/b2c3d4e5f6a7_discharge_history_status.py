"""add status and progress columns to discharge_history

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('discharge_history', sa.Column('status', sa.String(20), nullable=False, server_default='pending'))
    op.add_column('discharge_history', sa.Column('processed_reports', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('discharge_history', sa.Column('processed_bills', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('discharge_history', sa.Column('processed_prescriptions', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('discharge_history', 'processed_prescriptions')
    op.drop_column('discharge_history', 'processed_bills')
    op.drop_column('discharge_history', 'processed_reports')
    op.drop_column('discharge_history', 'status')
