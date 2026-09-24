"""attendance_finalisation_and_audit

Phase 7 - Faculty review, manual overrides, and transaction-safe finalisation workflow.
Adds session-level finalisation metadata, recommendation-level override fields,
and an attendance_audit_logs table to track all override and finalisation actions.

Revision ID: 009_attendance_finalisation_and_audit
Revises: 008_session_processing_evidence
Create Date: 2026-09-24 10:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009_attendance_finalisation_and_audit'
down_revision = '008_session_processing_evidence'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create attendance_audit_logs table
    op.create_table(
        'attendance_audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('previous_status', sa.String(length=30), nullable=True),
        sa.Column('new_status', sa.String(length=30), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('details_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['attendance_sessions.id'], name='fk_audit_session_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], name='fk_audit_student_id', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_audit_user_id', ondelete='SET NULL'),
    )
    with op.batch_alter_table('attendance_audit_logs', schema=None) as batch_op:
        batch_op.create_index('ix_attendance_audit_logs_session_id', ['session_id'], unique=False)
        batch_op.create_index('ix_attendance_audit_logs_student_id', ['student_id'], unique=False)
        batch_op.create_index('ix_attendance_audit_logs_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_attendance_audit_logs_action', ['action'], unique=False)

    # 2. Add finalisation columns to attendance_sessions
    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_finalised', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('finalised_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('finalised_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('finalisation_notes', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_attendance_sessions_finalised_by', 'users', ['finalised_by'], ['id'])

    # 3. Add override columns to attendance_recommendations
    with op.batch_alter_table('attendance_recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('final_status', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('is_overridden', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('override_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('overridden_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('overridden_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key('fk_attendance_recommendations_overridden_by', 'users', ['overridden_by'], ['id'])


def downgrade():
    # 3. Remove override columns from attendance_recommendations
    with op.batch_alter_table('attendance_recommendations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_attendance_recommendations_overridden_by', type_='foreignkey')
        batch_op.drop_column('overridden_at')
        batch_op.drop_column('overridden_by')
        batch_op.drop_column('override_reason')
        batch_op.drop_column('is_overridden')
        batch_op.drop_column('final_status')

    # 2. Remove finalisation columns from attendance_sessions
    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_attendance_sessions_finalised_by', type_='foreignkey')
        batch_op.drop_column('finalisation_notes')
        batch_op.drop_column('finalised_by')
        batch_op.drop_column('finalised_at')
        batch_op.drop_column('is_finalised')

    # 1. Drop attendance_audit_logs table
    with op.batch_alter_table('attendance_audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_attendance_audit_logs_action')
        batch_op.drop_index('ix_attendance_audit_logs_user_id')
        batch_op.drop_index('ix_attendance_audit_logs_student_id')
        batch_op.drop_index('ix_attendance_audit_logs_session_id')

    op.drop_table('attendance_audit_logs')
