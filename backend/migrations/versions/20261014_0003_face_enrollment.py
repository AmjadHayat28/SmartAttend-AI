"""face enrollment

Phase 4: validation metadata and review fields for student_face_images, and a
face-enrollment lifecycle on students (separate from account approval).
face_embeddings is intentionally untouched (Phase 6).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14 15:26:01.468453

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('student_face_images', schema=None) as batch_op:
        batch_op.add_column(sa.Column('validation_status', sa.Enum('pass', 'warning', 'fail', name='image_check_status', native_enum=False, create_constraint=True, length=32), server_default='pass', nullable=False))
        batch_op.add_column(sa.Column('validation_message', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('quality', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))
        batch_op.add_column(sa.Column('width', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('height', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('file_size', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_student_face_images_reviewed_by_id_users'), 'users', ['reviewed_by_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profile_photo_updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('face_enrollment_status', sa.Enum('not_started', 'incomplete', 'pending_review', 'approved', 'rejected', name='face_enrollment_status', native_enum=False, create_constraint=True, length=32), server_default='not_started', nullable=False))
        batch_op.add_column(sa.Column('face_submitted_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('face_reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('face_reviewed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('face_review_note', sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f('ix_students_face_enrollment_status'), ['face_enrollment_status'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_students_face_reviewed_by_id_users'), 'users', ['face_reviewed_by_id'], ['id'], ondelete='SET NULL')



def downgrade() -> None:
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_students_face_reviewed_by_id_users'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_students_face_enrollment_status'))
        # Drop the enum CHECK first: SQLite's batch rebuild would otherwise keep it and
        # fail on the now-missing column. On PostgreSQL this is a plain DROP CONSTRAINT.
        batch_op.drop_constraint(batch_op.f('ck_students_face_enrollment_status'), type_='check')
        batch_op.drop_column('face_review_note')
        batch_op.drop_column('face_reviewed_by_id')
        batch_op.drop_column('face_reviewed_at')
        batch_op.drop_column('face_submitted_at')
        batch_op.drop_column('face_enrollment_status')
        batch_op.drop_column('profile_photo_updated_at')

    with op.batch_alter_table('student_face_images', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_student_face_images_reviewed_by_id_users'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('ck_student_face_images_image_check_status'), type_='check')
        batch_op.drop_column('reviewed_by_id')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('updated_at')
        batch_op.drop_column('file_size')
        batch_op.drop_column('height')
        batch_op.drop_column('width')
        batch_op.drop_column('quality')
        batch_op.drop_column('validation_message')
        batch_op.drop_column('validation_status')

