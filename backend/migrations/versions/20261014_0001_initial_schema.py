"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-14 14:27:36.378193

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Baseline: schema as of Phase 2 (auth, academic structure, attendance, audit).
    op.create_table('departments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments')),
    sa.UniqueConstraint('name', name=op.f('uq_departments_name'))
    )
    with op.batch_alter_table('departments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_departments_code'), ['code'], unique=True)

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=150), nullable=False),
    sa.Column('role', sa.Enum('super_admin', 'hod', 'teacher', 'student', name='user_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending', 'active', 'suspended', 'rejected', name='account_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status_reason', sa.String(length=500), nullable=True),
    sa.Column('approved_by_id', sa.Integer(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], name=op.f('fk_users_approved_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_role'), ['role'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_status'), ['status'], unique=False)

    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('entity', sa.String(length=100), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('old_value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('new_value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_audit_logs_department_id_departments'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_logs_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_logs_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_timestamp'), ['timestamp'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_user_id'), ['user_id'], unique=False)

    op.create_table('batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('start_year', sa.SmallInteger(), nullable=False),
    sa.Column('end_year', sa.SmallInteger(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('end_year IS NULL OR end_year >= start_year', name=op.f('ck_batches_year_order')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_batches_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_batches')),
    sa.UniqueConstraint('department_id', 'name', name=op.f('uq_batches_department_id_name'))
    )
    with op.batch_alter_table('batches', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_batches_department_id'), ['department_id'], unique=False)

    op.create_table('courses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('credit_hours', sa.SmallInteger(), nullable=False),
    sa.Column('is_lab', sa.Boolean(), nullable=False),
    sa.Column('semester_number', sa.SmallInteger(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('credit_hours >= 0', name=op.f('ck_courses_credit_hours_positive')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_courses_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_courses')),
    sa.UniqueConstraint('department_id', 'code', name=op.f('uq_courses_department_id_code'))
    )
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_courses_department_id'), ['department_id'], unique=False)

    op.create_table('hods',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.String(length=50), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('appointed_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_hods_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_hods_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hods')),
    sa.UniqueConstraint('department_id', name=op.f('uq_hods_department_id')),
    sa.UniqueConstraint('employee_id', name=op.f('uq_hods_employee_id')),
    sa.UniqueConstraint('user_id', name=op.f('uq_hods_user_id'))
    )
    op.create_table('teachers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.String(length=50), nullable=False),
    sa.Column('designation', sa.String(length=100), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_teachers_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_teachers_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_teachers')),
    sa.UniqueConstraint('employee_id', name=op.f('uq_teachers_employee_id')),
    sa.UniqueConstraint('user_id', name=op.f('uq_teachers_user_id'))
    )
    with op.batch_alter_table('teachers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_teachers_department_id'), ['department_id'], unique=False)

    op.create_table('semesters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.SmallInteger(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('number BETWEEN 1 AND 12', name=op.f('ck_semesters_number_range')),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name=op.f('fk_semesters_batch_id_batches'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_semesters_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_semesters')),
    sa.UniqueConstraint('batch_id', 'number', name=op.f('uq_semesters_batch_id_number'))
    )
    with op.batch_alter_table('semesters', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_semesters_batch_id'), ['batch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_semesters_department_id'), ['department_id'], unique=False)

    op.create_table('sections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('semester_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=20), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_sections_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['semester_id'], ['semesters.id'], name=op.f('fk_sections_semester_id_semesters'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sections')),
    sa.UniqueConstraint('semester_id', 'name', name=op.f('uq_sections_semester_id_name'))
    )
    with op.batch_alter_table('sections', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sections_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sections_semester_id'), ['semester_id'], unique=False)

    op.create_table('students',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('semester_id', sa.Integer(), nullable=False),
    sa.Column('section_id', sa.Integer(), nullable=False),
    sa.Column('registration_no', sa.String(length=50), nullable=False),
    sa.Column('profile_photo_path', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name=op.f('fk_students_batch_id_batches'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_students_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_students_section_id_sections'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['semester_id'], ['semesters.id'], name=op.f('fk_students_semester_id_semesters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_students_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_students')),
    sa.UniqueConstraint('user_id', name=op.f('uq_students_user_id'))
    )
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_students_batch_id'), ['batch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_students_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_students_registration_no'), ['registration_no'], unique=True)
        batch_op.create_index(batch_op.f('ix_students_section_id'), ['section_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_students_semester_id'), ['semester_id'], unique=False)

    op.create_table('teacher_course_assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('teacher_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('section_id', sa.Integer(), nullable=False),
    sa.Column('semester_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('assigned_by_id', sa.Integer(), nullable=True),
    sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], name=op.f('fk_teacher_course_assignments_assigned_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_teacher_course_assignments_course_id_courses'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_teacher_course_assignments_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_teacher_course_assignments_section_id_sections'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['semester_id'], ['semesters.id'], name=op.f('fk_teacher_course_assignments_semester_id_semesters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], name=op.f('fk_teacher_course_assignments_teacher_id_teachers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_teacher_course_assignments')),
    sa.UniqueConstraint('teacher_id', 'course_id', 'section_id', name=op.f('uq_teacher_course_assignments_teacher_id_course_id_section_id'))
    )
    with op.batch_alter_table('teacher_course_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_teacher_course_assignments_course_id'), ['course_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_teacher_course_assignments_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_teacher_course_assignments_section_id'), ['section_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_teacher_course_assignments_teacher_id'), ['teacher_id'], unique=False)

    op.create_table('attendance_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('assignment_id', sa.Integer(), nullable=True),
    sa.Column('teacher_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('section_id', sa.Integer(), nullable=False),
    sa.Column('semester_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('session_date', sa.Date(), nullable=False),
    sa.Column('session_number', sa.SmallInteger(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('status', sa.Enum('draft', 'submitted', name='session_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('photo_paths', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('faces_detected', sa.Integer(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('session_number >= 1', name=op.f('ck_attendance_sessions_session_number_positive')),
    sa.ForeignKeyConstraint(['assignment_id'], ['teacher_course_assignments.id'], name=op.f('fk_attendance_sessions_assignment_id_teacher_course_assignments'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_attendance_sessions_course_id_courses'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_attendance_sessions_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_attendance_sessions_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_attendance_sessions_section_id_sections'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['semester_id'], ['semesters.id'], name=op.f('fk_attendance_sessions_semester_id_semesters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], name=op.f('fk_attendance_sessions_teacher_id_teachers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_sessions')),
    sa.UniqueConstraint('course_id', 'section_id', 'session_date', 'session_number', name=op.f('uq_attendance_sessions_course_id_section_id_session_date_session_number'))
    )
    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attendance_sessions_course_id'), ['course_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_sessions_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_sessions_section_id'), ['section_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_sessions_session_date'), ['session_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_sessions_teacher_id'), ['teacher_id'], unique=False)

    op.create_table('student_course_enrollments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('section_id', sa.Integer(), nullable=False),
    sa.Column('semester_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_student_course_enrollments_course_id_courses'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_student_course_enrollments_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_student_course_enrollments_section_id_sections'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['semester_id'], ['semesters.id'], name=op.f('fk_student_course_enrollments_semester_id_semesters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_student_course_enrollments_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_student_course_enrollments')),
    sa.UniqueConstraint('student_id', 'course_id', 'semester_id', name=op.f('uq_student_course_enrollments_student_id_course_id_semester_id'))
    )
    with op.batch_alter_table('student_course_enrollments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_student_course_enrollments_course_id'), ['course_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_student_course_enrollments_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_student_course_enrollments_section_id'), ['section_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_student_course_enrollments_student_id'), ['student_id'], unique=False)

    op.create_table('student_face_images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('image_path', sa.String(length=500), nullable=False),
    sa.Column('image_type', sa.Enum('front', 'left', 'right', 'extra', name='face_image_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('is_usable', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_student_face_images_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_student_face_images'))
    )
    with op.batch_alter_table('student_face_images', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_student_face_images_student_id'), ['student_id'], unique=False)

    op.create_table('attendance_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('teacher_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('semester_id', sa.Integer(), nullable=False),
    sa.Column('section_id', sa.Integer(), nullable=False),
    sa.Column('attendance_date', sa.Date(), nullable=False),
    sa.Column('attendance_time', sa.Time(), nullable=True),
    sa.Column('session_number', sa.SmallInteger(), nullable=False),
    sa.Column('status', sa.Enum('present', 'absent', 'late', 'excused', name='attendance_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('method', sa.Enum('face_recognition', 'manual', 'hod_override', name='attendance_method', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('last_modified_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('confidence IS NULL OR (confidence >= 0 AND confidence <= 1)', name=op.f('ck_attendance_records_confidence_range')),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_attendance_records_course_id_courses'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_attendance_records_created_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_attendance_records_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['last_modified_by_id'], ['users.id'], name=op.f('fk_attendance_records_last_modified_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_attendance_records_section_id_sections'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['semester_id'], ['semesters.id'], name=op.f('fk_attendance_records_semester_id_semesters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['session_id'], ['attendance_sessions.id'], name=op.f('fk_attendance_records_session_id_attendance_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_attendance_records_student_id_students'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], name=op.f('fk_attendance_records_teacher_id_teachers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_records')),
    sa.UniqueConstraint('session_id', 'student_id', name=op.f('uq_attendance_records_session_id_student_id')),
    sa.UniqueConstraint('student_id', 'course_id', 'section_id', 'attendance_date', 'session_number', name='uq_attendance_records_student_course_section_date_session')
    )
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attendance_records_attendance_date'), ['attendance_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_records_course_id'), ['course_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_records_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_records_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_records_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_records_student_id'), ['student_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_attendance_records_teacher_id'), ['teacher_id'], unique=False)

    op.create_table('face_embeddings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('face_image_id', sa.Integer(), nullable=False),
    sa.Column('embedding_vector', sa.LargeBinary(), nullable=False),
    sa.Column('dimension', sa.Integer(), nullable=False),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['face_image_id'], ['student_face_images.id'], name=op.f('fk_face_embeddings_face_image_id_student_face_images'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_face_embeddings_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_face_embeddings')),
    sa.UniqueConstraint('face_image_id', name=op.f('uq_face_embeddings_face_image_id'))
    )
    with op.batch_alter_table('face_embeddings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_face_embeddings_student_id'), ['student_id'], unique=False)

    op.create_table('attendance_modifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('modified_by_id', sa.Integer(), nullable=False),
    sa.Column('modifier_role', sa.Enum('super_admin', 'hod', 'teacher', 'student', name='user_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('old_value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('new_value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('modified_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['modified_by_id'], ['users.id'], name=op.f('fk_attendance_modifications_modified_by_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['record_id'], ['attendance_records.id'], name=op.f('fk_attendance_modifications_record_id_attendance_records'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attendance_modifications'))
    )
    with op.batch_alter_table('attendance_modifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_attendance_modifications_record_id'), ['record_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    # Baseline: schema as of Phase 2 (auth, academic structure, attendance, audit).
    with op.batch_alter_table('attendance_modifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attendance_modifications_record_id'))

    op.drop_table('attendance_modifications')
    with op.batch_alter_table('face_embeddings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_face_embeddings_student_id'))

    op.drop_table('face_embeddings')
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attendance_records_teacher_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_records_student_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_records_status'))
        batch_op.drop_index(batch_op.f('ix_attendance_records_session_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_records_department_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_records_course_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_records_attendance_date'))

    op.drop_table('attendance_records')
    with op.batch_alter_table('student_face_images', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_student_face_images_student_id'))

    op.drop_table('student_face_images')
    with op.batch_alter_table('student_course_enrollments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_student_course_enrollments_student_id'))
        batch_op.drop_index(batch_op.f('ix_student_course_enrollments_section_id'))
        batch_op.drop_index(batch_op.f('ix_student_course_enrollments_department_id'))
        batch_op.drop_index(batch_op.f('ix_student_course_enrollments_course_id'))

    op.drop_table('student_course_enrollments')
    with op.batch_alter_table('attendance_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_attendance_sessions_teacher_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_sessions_session_date'))
        batch_op.drop_index(batch_op.f('ix_attendance_sessions_section_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_sessions_department_id'))
        batch_op.drop_index(batch_op.f('ix_attendance_sessions_course_id'))

    op.drop_table('attendance_sessions')
    with op.batch_alter_table('teacher_course_assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_teacher_course_assignments_teacher_id'))
        batch_op.drop_index(batch_op.f('ix_teacher_course_assignments_section_id'))
        batch_op.drop_index(batch_op.f('ix_teacher_course_assignments_department_id'))
        batch_op.drop_index(batch_op.f('ix_teacher_course_assignments_course_id'))

    op.drop_table('teacher_course_assignments')
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_students_semester_id'))
        batch_op.drop_index(batch_op.f('ix_students_section_id'))
        batch_op.drop_index(batch_op.f('ix_students_registration_no'))
        batch_op.drop_index(batch_op.f('ix_students_department_id'))
        batch_op.drop_index(batch_op.f('ix_students_batch_id'))

    op.drop_table('students')
    with op.batch_alter_table('sections', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sections_semester_id'))
        batch_op.drop_index(batch_op.f('ix_sections_department_id'))

    op.drop_table('sections')
    with op.batch_alter_table('semesters', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_semesters_department_id'))
        batch_op.drop_index(batch_op.f('ix_semesters_batch_id'))

    op.drop_table('semesters')
    with op.batch_alter_table('teachers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_teachers_department_id'))

    op.drop_table('teachers')
    op.drop_table('hods')
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_courses_department_id'))

    op.drop_table('courses')
    with op.batch_alter_table('batches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_batches_department_id'))

    op.drop_table('batches')
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_logs_user_id'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_timestamp'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_department_id'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_action'))

    op.drop_table('audit_logs')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_status'))
        batch_op.drop_index(batch_op.f('ix_users_role'))
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('departments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_departments_code'))

    op.drop_table('departments')
