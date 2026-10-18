"""attendance workflow

Phase 5 (manual attendance, no recognition):
- attendance_sessions: lifecycle draft → finalized | cancelled (was draft/submitted);
  one *non-cancelled* session per course/section/date/session-number (partial unique index,
  so a cancelled draft frees its slot); optimistic-lock `version`; session note;
  finalized/cancelled by + at; `submitted_at` renamed to `finalized_at`; unused
  `photo_paths` JSON dropped (photos now live in attendance_session_images).
- attendance_records: `status` nullable (= not marked yet, drafts only); per-student note;
  the 5-column duplicate constraint is replaced by UNIQUE(session_id, student_id) + the
  sessions' active-slot index (needed so a cancelled session's rows don't block a new one).
- attendance_session_images: classroom-photo metadata (files stay on disk).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_SLOT_UQ = 'uq_attendance_sessions_course_id_section_id_session_date_session_number'
_OLD_RECORD_UQ = 'uq_attendance_records_student_course_section_date_session'
_STATUS_CK = 'ck_attendance_sessions_session_status'


def upgrade() -> None:
    op.create_table(
        'attendance_session_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['attendance_sessions.id'],
                                name=op.f('fk_attendance_session_images_session_id_attendance_sessions'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'],
                                name=op.f('fk_attendance_session_images_uploaded_by_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_session_images')),
    )
    with op.batch_alter_table('attendance_session_images', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attendance_session_images_session_id'), ['session_id'], unique=False)

    # Status values change: drop the old CHECK, migrate data, add the new CHECK.
    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_STATUS_CK), type_='check')
    op.execute("UPDATE attendance_sessions SET status = 'finalized' WHERE status = 'submitted'")

    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.create_check_constraint(batch_op.f(_STATUS_CK), "status IN ('draft', 'finalized', 'cancelled')")
        batch_op.alter_column('submitted_at', new_column_name='finalized_at',
                              existing_type=sa.DateTime(timezone=True), existing_nullable=True)
        batch_op.add_column(sa.Column('note', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('version', sa.Integer(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('finalized_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('cancelled_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cancel_reason', sa.String(length=300), nullable=True))
        batch_op.create_check_constraint(batch_op.f('ck_attendance_sessions_version_positive'), 'version >= 1')
        batch_op.create_foreign_key(batch_op.f('fk_attendance_sessions_finalized_by_id_users'), 'users',
                                    ['finalized_by_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key(batch_op.f('fk_attendance_sessions_cancelled_by_id_users'), 'users',
                                    ['cancelled_by_id'], ['id'], ondelete='SET NULL')
        batch_op.drop_constraint(batch_op.f(_OLD_SLOT_UQ), type_='unique')
        batch_op.create_index(batch_op.f('ix_attendance_sessions_status'), ['status'], unique=False)
        batch_op.create_index('uq_attendance_sessions_active_slot',
                              ['course_id', 'section_id', 'session_date', 'session_number'], unique=True,
                              postgresql_where=sa.text("status <> 'cancelled'"),
                              sqlite_where=sa.text("status <> 'cancelled'"))
        batch_op.drop_column('photo_paths')

    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('note', sa.String(length=200), nullable=True))
        batch_op.alter_column('status', existing_type=sa.String(length=32), nullable=True)
        batch_op.drop_constraint(batch_op.f(_OLD_RECORD_UQ), type_='unique')


def downgrade() -> None:
    bind = op.get_bind()
    blockers = {
        "cancelled sessions": "SELECT COUNT(*) FROM attendance_sessions WHERE status = 'cancelled'",
        "unmarked attendance records": "SELECT COUNT(*) FROM attendance_records WHERE status IS NULL",
    }
    for label, sql in blockers.items():
        count = bind.execute(sa.text(sql)).scalar()
        if count:
            raise RuntimeError(f"Cannot downgrade: {count} {label} cannot be represented in revision 0003. "
                               "Finalize or remove them first.")

    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.create_unique_constraint(batch_op.f(_OLD_RECORD_UQ),
                                          ['student_id', 'course_id', 'section_id', 'attendance_date', 'session_number'])
        batch_op.alter_column('status', existing_type=sa.String(length=32), nullable=False)
        batch_op.drop_column('note')

    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_paths', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()),
                                                                            'postgresql'), nullable=True))
        batch_op.drop_index('uq_attendance_sessions_active_slot', postgresql_where=sa.text("status <> 'cancelled'"),
                            sqlite_where=sa.text("status <> 'cancelled'"))
        batch_op.drop_index(batch_op.f('ix_attendance_sessions_status'))
        batch_op.create_unique_constraint(batch_op.f(_OLD_SLOT_UQ),
                                          ['course_id', 'section_id', 'session_date', 'session_number'])
        batch_op.drop_constraint(batch_op.f('fk_attendance_sessions_cancelled_by_id_users'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('fk_attendance_sessions_finalized_by_id_users'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('ck_attendance_sessions_version_positive'), type_='check')
        batch_op.drop_column('cancel_reason')
        batch_op.drop_column('cancelled_by_id')
        batch_op.drop_column('cancelled_at')
        batch_op.drop_column('finalized_by_id')
        batch_op.drop_column('version')
        batch_op.drop_column('note')
        batch_op.alter_column('finalized_at', new_column_name='submitted_at',
                              existing_type=sa.DateTime(timezone=True), existing_nullable=True)
        batch_op.drop_constraint(batch_op.f(_STATUS_CK), type_='check')
    op.execute("UPDATE attendance_sessions SET status = 'submitted' WHERE status = 'finalized'")
    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.create_check_constraint(batch_op.f(_STATUS_CK), "status IN ('draft', 'submitted')")

    with op.batch_alter_table('attendance_session_images', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attendance_session_images_session_id'))
    op.drop_table('attendance_session_images')
