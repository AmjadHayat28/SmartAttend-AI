"""face recognition

Phase 6:
- attendance_recognition_runs / attendance_recognition_faces: one row per recognition run and
  per detected face (box, suggestion, scores, teacher decision). No vectors, no face pixels.
- face_embeddings: model_version, source_updated_at (freshness), det_score.
- attendance_records: recognition_run_id / recognition_face_id, and the new method value
  'face_recognition_confirmed' (teacher accepted/assigned an AI suggestion).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14 17:19:15.729598

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('attendance_recognition_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('processing', 'completed', 'completed_with_warnings', 'failed', name='recognition_run_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('started_by_id', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('model_version', sa.String(length=100), nullable=False),
    sa.Column('thresholds', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('image_count', sa.Integer(), nullable=False),
    sa.Column('faces_detected', sa.Integer(), nullable=False),
    sa.Column('confident_count', sa.Integer(), nullable=False),
    sa.Column('low_confidence_count', sa.Integer(), nullable=False),
    sa.Column('ambiguous_count', sa.Integer(), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), nullable=False),
    sa.Column('unknown_count', sa.Integer(), nullable=False),
    sa.Column('students_recognized', sa.Integer(), nullable=False),
    sa.Column('roster_size', sa.Integer(), nullable=False),
    sa.Column('eligible_count', sa.Integer(), nullable=False),
    sa.Column('applied_count', sa.Integer(), nullable=False),
    sa.Column('preserved_count', sa.Integer(), nullable=False),
    sa.Column('missing_student_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('warnings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('error_message', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['attendance_sessions.id'], name=op.f('fk_attendance_recognition_runs_session_id_attendance_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['started_by_id'], ['users.id'], name=op.f('fk_attendance_recognition_runs_started_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_recognition_runs'))
    )
    with op.batch_alter_table('attendance_recognition_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attendance_recognition_runs_session_id'), ['session_id'], unique=False)

    op.create_table('attendance_recognition_faces',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=False),
    sa.Column('face_index', sa.Integer(), nullable=False),
    sa.Column('bbox_x', sa.Integer(), nullable=False),
    sa.Column('bbox_y', sa.Integer(), nullable=False),
    sa.Column('bbox_w', sa.Integer(), nullable=False),
    sa.Column('bbox_h', sa.Integer(), nullable=False),
    sa.Column('det_score', sa.Float(), nullable=False),
    sa.Column('category', sa.Enum('confident', 'low_confidence', 'ambiguous', 'duplicate', 'no_match', name='recognition_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=True),
    sa.Column('similarity', sa.Float(), nullable=True),
    sa.Column('second_student_id', sa.Integer(), nullable=True),
    sa.Column('second_similarity', sa.Float(), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('decision', sa.Enum('applied', 'manual_kept', 'pending', 'accepted', 'assigned', 'rejected', 'none', name='face_decision', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('assigned_student_id', sa.Integer(), nullable=True),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assigned_student_id'], ['students.id'], name=op.f('fk_attendance_recognition_faces_assigned_student_id_students'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], name=op.f('fk_attendance_recognition_faces_decided_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_id'], ['attendance_session_images.id'], name=op.f('fk_attendance_recognition_faces_image_id_attendance_session_images'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['attendance_recognition_runs.id'], name=op.f('fk_attendance_recognition_faces_run_id_attendance_recognition_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['second_student_id'], ['students.id'], name=op.f('fk_attendance_recognition_faces_second_student_id_students'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_attendance_recognition_faces_student_id_students'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_recognition_faces'))
    )
    with op.batch_alter_table('attendance_recognition_faces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attendance_recognition_faces_image_id'), ['image_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_recognition_faces_run_id'), ['run_id'], unique=False)

    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recognition_run_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('recognition_face_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_attendance_records_recognition_run_id_attendance_recognition_runs'), 'attendance_recognition_runs', ['recognition_run_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key(batch_op.f('fk_attendance_records_recognition_face_id_attendance_recognition_faces'), 'attendance_recognition_faces', ['recognition_face_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('face_embeddings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model_version', sa.String(length=100), server_default='', nullable=False))
        batch_op.add_column(sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('det_score', sa.Float(), nullable=True))


    # New attendance method value: rebuild the enum CHECK.
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('ck_attendance_records_attendance_method'), type_='check')
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.create_check_constraint(
            batch_op.f('ck_attendance_records_attendance_method'),
            "method IN ('face_recognition', 'face_recognition_confirmed', 'manual', 'hod_override')")


def downgrade() -> None:
    # Confirmed AI marks become plain face_recognition marks in revision 0004.
    op.execute("UPDATE attendance_records SET method = 'face_recognition' WHERE method = 'face_recognition_confirmed'")
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('ck_attendance_records_attendance_method'), type_='check')
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.create_check_constraint(
            batch_op.f('ck_attendance_records_attendance_method'),
            "method IN ('face_recognition', 'manual', 'hod_override')")

    with op.batch_alter_table('face_embeddings', schema=None) as batch_op:
        batch_op.drop_column('det_score')
        batch_op.drop_column('source_updated_at')
        batch_op.drop_column('model_version')

    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_attendance_records_recognition_face_id_attendance_recognition_faces'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('fk_attendance_records_recognition_run_id_attendance_recognition_runs'), type_='foreignkey')
        batch_op.drop_column('recognition_face_id')
        batch_op.drop_column('recognition_run_id')

    with op.batch_alter_table('attendance_recognition_faces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attendance_recognition_faces_run_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_recognition_faces_image_id'))

    op.drop_table('attendance_recognition_faces')
    with op.batch_alter_table('attendance_recognition_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attendance_recognition_runs_session_id'))

    op.drop_table('attendance_recognition_runs')
