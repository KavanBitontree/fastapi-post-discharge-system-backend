"""add discharge_history table

Revision ID: a1b2c3d4e5f6
Revises: 4c64f8d345b8
Create Date: 2026-03-10

Changes:
- Create discharge_history table (id, patient_id FK, discharge_date)
- Remove discharge_date from patients table
- Add discharge_id FK to: bills, reports, report_descriptions, medications, patient_doctor
- Drop patient_id FK from: bills, reports, report_descriptions, medications, patient_doctor
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '8f1079064424'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create discharge_history table ────────────────────────────────────
    op.create_table(
        'discharge_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('discharge_date', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE', onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_discharge_history_id', 'discharge_history', ['id'])
    op.create_index('ix_discharge_history_patient_id', 'discharge_history', ['patient_id'])

    # ── 2. Migrate existing patients into discharge_history ───────────────────
    # For each patient that has a discharge_date (or is otherwise existing),
    # create one discharge_history row so existing FK data can be migrated.
    op.execute("""
        INSERT INTO discharge_history (patient_id, discharge_date)
        SELECT id, discharge_date FROM patients
    """)

    # ── 3. bills: add discharge_id, migrate, drop patient_id ─────────────────
    op.add_column('bills', sa.Column('discharge_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE bills b
        SET discharge_id = dh.id
        FROM discharge_history dh
        WHERE dh.patient_id = b.patient_id
    """)
    op.alter_column('bills', 'discharge_id', nullable=False)
    op.create_index('ix_bills_discharge_id', 'bills', ['discharge_id'])
    op.create_foreign_key('fk_bills_discharge_id', 'bills', 'discharge_history', ['discharge_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('bills_patient_id_fkey', 'bills', type_='foreignkey')
    op.drop_index('ix_bills_patient_id', table_name='bills')
    op.drop_column('bills', 'patient_id')

    # ── 4. reports: add discharge_id, migrate, drop patient_id ───────────────
    op.add_column('reports', sa.Column('discharge_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE reports r
        SET discharge_id = dh.id
        FROM discharge_history dh
        WHERE dh.patient_id = r.patient_id
    """)
    op.alter_column('reports', 'discharge_id', nullable=False)
    op.create_index('ix_reports_discharge_id', 'reports', ['discharge_id'])
    op.create_foreign_key('fk_reports_discharge_id', 'reports', 'discharge_history', ['discharge_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('reports_patient_id_fkey', 'reports', type_='foreignkey')
    op.drop_index('ix_reports_patient_id', table_name='reports')
    op.drop_column('reports', 'patient_id')

    # ── 5. report_descriptions: add discharge_id, migrate, drop patient_id ───
    op.add_column('report_descriptions', sa.Column('discharge_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE report_descriptions rd
        SET discharge_id = r.discharge_id
        FROM reports r
        WHERE r.id = rd.report_id
    """)
    op.alter_column('report_descriptions', 'discharge_id', nullable=False)
    op.create_index('ix_report_descriptions_discharge_id', 'report_descriptions', ['discharge_id'])
    op.create_foreign_key('fk_report_descriptions_discharge_id', 'report_descriptions', 'discharge_history', ['discharge_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('report_descriptions_patient_id_fkey', 'report_descriptions', type_='foreignkey')
    op.drop_index('ix_report_descriptions_patient_id', table_name='report_descriptions')
    op.drop_column('report_descriptions', 'patient_id')

    # ── 6. medications: add discharge_id, migrate, drop patient_id ───────────
    op.add_column('medications', sa.Column('discharge_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE medications m
        SET discharge_id = dh.id
        FROM discharge_history dh
        WHERE dh.patient_id = m.patient_id
    """)
    op.alter_column('medications', 'discharge_id', nullable=False)
    op.create_index('ix_medications_discharge_id', 'medications', ['discharge_id'])
    op.create_foreign_key('fk_medications_discharge_id', 'medications', 'discharge_history', ['discharge_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('medications_patient_id_fkey', 'medications', type_='foreignkey')
    op.drop_index('ix_medications_patient_id', table_name='medications')
    op.drop_column('medications', 'patient_id')

    # ── 7. patient_doctor: add discharge_id, migrate, drop patient_id ────────
    op.add_column('patient_doctor', sa.Column('discharge_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE patient_doctor pd
        SET discharge_id = dh.id
        FROM discharge_history dh
        WHERE dh.patient_id = pd.patient_id
    """)
    op.alter_column('patient_doctor', 'discharge_id', nullable=False)
    op.create_index('ix_patient_doctor_discharge_id', 'patient_doctor', ['discharge_id'])
    op.create_foreign_key('fk_patient_doctor_discharge_id', 'patient_doctor', 'discharge_history', ['discharge_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('patient_doctor_patient_id_fkey', 'patient_doctor', type_='foreignkey')
    op.drop_index('ix_patient_doctor_patient_id', table_name='patient_doctor')
    op.drop_column('patient_doctor', 'patient_id')

    # ── 8. Remove discharge_date from patients ────────────────────────────────
    op.drop_column('patients', 'discharge_date')


def downgrade() -> None:
    # ── Restore discharge_date on patients ────────────────────────────────────
    op.add_column('patients', sa.Column('discharge_date', sa.Date(), nullable=True))
    op.execute("""
        UPDATE patients p
        SET discharge_date = dh.discharge_date
        FROM discharge_history dh
        WHERE dh.patient_id = p.id
    """)

    # ── Restore patient_id on patient_doctor ─────────────────────────────────
    op.add_column('patient_doctor', sa.Column('patient_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE patient_doctor pd
        SET patient_id = dh.patient_id
        FROM discharge_history dh
        WHERE dh.id = pd.discharge_id
    """)
    op.alter_column('patient_doctor', 'patient_id', nullable=False)
    op.create_index('ix_patient_doctor_patient_id', 'patient_doctor', ['patient_id'])
    op.create_foreign_key('patient_doctor_patient_id_fkey', 'patient_doctor', 'patients', ['patient_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('fk_patient_doctor_discharge_id', 'patient_doctor', type_='foreignkey')
    op.drop_index('ix_patient_doctor_discharge_id', table_name='patient_doctor')
    op.drop_column('patient_doctor', 'discharge_id')

    # ── Restore patient_id on medications ─────────────────────────────────────
    op.add_column('medications', sa.Column('patient_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE medications m
        SET patient_id = dh.patient_id
        FROM discharge_history dh
        WHERE dh.id = m.discharge_id
    """)
    op.alter_column('medications', 'patient_id', nullable=False)
    op.create_index('ix_medications_patient_id', 'medications', ['patient_id'])
    op.create_foreign_key('medications_patient_id_fkey', 'medications', 'patients', ['patient_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('fk_medications_discharge_id', 'medications', type_='foreignkey')
    op.drop_index('ix_medications_discharge_id', table_name='medications')
    op.drop_column('medications', 'discharge_id')

    # ── Restore patient_id on report_descriptions ────────────────────────────
    op.add_column('report_descriptions', sa.Column('patient_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE report_descriptions rd
        SET patient_id = dh.patient_id
        FROM discharge_history dh
        WHERE dh.id = rd.discharge_id
    """)
    op.alter_column('report_descriptions', 'patient_id', nullable=False)
    op.create_index('ix_report_descriptions_patient_id', 'report_descriptions', ['patient_id'])
    op.create_foreign_key('report_descriptions_patient_id_fkey', 'report_descriptions', 'patients', ['patient_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('fk_report_descriptions_discharge_id', 'report_descriptions', type_='foreignkey')
    op.drop_index('ix_report_descriptions_discharge_id', table_name='report_descriptions')
    op.drop_column('report_descriptions', 'discharge_id')

    # ── Restore patient_id on reports ─────────────────────────────────────────
    op.add_column('reports', sa.Column('patient_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE reports r
        SET patient_id = dh.patient_id
        FROM discharge_history dh
        WHERE dh.id = r.discharge_id
    """)
    op.alter_column('reports', 'patient_id', nullable=False)
    op.create_index('ix_reports_patient_id', 'reports', ['patient_id'])
    op.create_foreign_key('reports_patient_id_fkey', 'reports', 'patients', ['patient_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('fk_reports_discharge_id', 'reports', type_='foreignkey')
    op.drop_index('ix_reports_discharge_id', table_name='reports')
    op.drop_column('reports', 'discharge_id')

    # ── Restore patient_id on bills ───────────────────────────────────────────
    op.add_column('bills', sa.Column('patient_id', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE bills b
        SET patient_id = dh.patient_id
        FROM discharge_history dh
        WHERE dh.id = b.discharge_id
    """)
    op.alter_column('bills', 'patient_id', nullable=False)
    op.create_index('ix_bills_patient_id', 'bills', ['patient_id'])
    op.create_foreign_key('bills_patient_id_fkey', 'bills', 'patients', ['patient_id'], ['id'], ondelete='CASCADE', onupdate='CASCADE')
    op.drop_constraint('fk_bills_discharge_id', 'bills', type_='foreignkey')
    op.drop_index('ix_bills_discharge_id', table_name='bills')
    op.drop_column('bills', 'discharge_id')

    # ── Drop discharge_history ────────────────────────────────────────────────
    op.drop_index('ix_discharge_history_patient_id', table_name='discharge_history')
    op.drop_index('ix_discharge_history_id', table_name='discharge_history')
    op.drop_table('discharge_history')
