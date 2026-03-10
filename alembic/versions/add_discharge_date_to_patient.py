"""Add discharge_date column to patient table

Revision ID: add_discharge_date
Revises: e0b3c88ab300
Create Date: 2026-03-10 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_discharge_date'
down_revision = 'e0b3c88ab300'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add discharge_date column to patients table
    op.add_column('patients', sa.Column('discharge_date', sa.Date(), nullable=True))


def downgrade() -> None:
    # Remove discharge_date column from patients table
    op.drop_column('patients', 'discharge_date')
