-- SmartClass AI Attendance — PostgreSQL schema
-- GENERATED from SQLAlchemy models by backend/app/scripts/export_schema.py. Do not edit by hand.
-- Apply with: psql -U smartclass -d smartclass_db -f database/schema.sql
-- (or let the app create tables: uv run python -m backend.app.database.init_db)

CREATE TABLE departments (
	id SERIAL NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	code VARCHAR(20) NOT NULL, 
	description TEXT, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_departments PRIMARY KEY (id), 
	CONSTRAINT uq_departments_name UNIQUE (name)
);
CREATE UNIQUE INDEX ix_departments_code ON departments (code);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	full_name VARCHAR(150) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	status_reason VARCHAR(500), 
	approved_by_id INTEGER, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	token_version INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT ck_users_user_role CHECK (role IN ('super_admin', 'hod', 'teacher', 'student')), 
	CONSTRAINT ck_users_account_status CHECK (status IN ('pending', 'active', 'suspended', 'rejected')), 
	CONSTRAINT fk_users_approved_by_id_users FOREIGN KEY(approved_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_users_role ON users (role);
CREATE INDEX ix_users_status ON users (status);

CREATE TABLE audit_logs (
	id SERIAL NOT NULL, 
	user_id INTEGER, 
	department_id INTEGER, 
	action VARCHAR(100) NOT NULL, 
	entity VARCHAR(100) NOT NULL, 
	entity_id VARCHAR(64), 
	old_value JSONB, 
	new_value JSONB, 
	ip_address VARCHAR(45), 
	user_agent VARCHAR(300), 
	timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
	CONSTRAINT fk_audit_logs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_audit_logs_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE SET NULL
);
CREATE INDEX ix_audit_logs_action ON audit_logs (action);
CREATE INDEX ix_audit_logs_department_id ON audit_logs (department_id);
CREATE INDEX ix_audit_logs_timestamp ON audit_logs (timestamp);
CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id);

CREATE TABLE batches (
	id SERIAL NOT NULL, 
	department_id INTEGER NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	start_year SMALLINT NOT NULL, 
	end_year SMALLINT, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_batches PRIMARY KEY (id), 
	CONSTRAINT uq_batches_department_id_name UNIQUE (department_id, name), 
	CONSTRAINT ck_batches_year_order CHECK (end_year IS NULL OR end_year >= start_year), 
	CONSTRAINT fk_batches_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT
);
CREATE INDEX ix_batches_department_id ON batches (department_id);

CREATE TABLE courses (
	id SERIAL NOT NULL, 
	department_id INTEGER NOT NULL, 
	code VARCHAR(20) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	credit_hours SMALLINT NOT NULL, 
	is_lab BOOLEAN NOT NULL, 
	semester_number SMALLINT, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_courses PRIMARY KEY (id), 
	CONSTRAINT uq_courses_department_id_code UNIQUE (department_id, code), 
	CONSTRAINT ck_courses_credit_hours_positive CHECK (credit_hours >= 0), 
	CONSTRAINT fk_courses_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT
);
CREATE INDEX ix_courses_department_id ON courses (department_id);

CREATE TABLE hods (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	is_current BOOLEAN DEFAULT true NOT NULL, 
	employee_id VARCHAR(50) NOT NULL, 
	phone VARCHAR(30), 
	appointed_on DATE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_hods PRIMARY KEY (id), 
	CONSTRAINT uq_hods_user_id UNIQUE (user_id), 
	CONSTRAINT fk_hods_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_hods_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_hods_employee_id UNIQUE (employee_id)
);
CREATE INDEX ix_hods_department_id ON hods (department_id);
CREATE UNIQUE INDEX uq_hods_current_department ON hods (department_id) WHERE is_current;

CREATE TABLE teachers (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	employee_id VARCHAR(50) NOT NULL, 
	designation VARCHAR(100), 
	phone VARCHAR(30), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_teachers PRIMARY KEY (id), 
	CONSTRAINT uq_teachers_user_id UNIQUE (user_id), 
	CONSTRAINT fk_teachers_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_teachers_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_teachers_employee_id UNIQUE (employee_id)
);
CREATE INDEX ix_teachers_department_id ON teachers (department_id);

CREATE TABLE semesters (
	id SERIAL NOT NULL, 
	batch_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	number SMALLINT NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	start_date DATE, 
	end_date DATE, 
	is_current BOOLEAN NOT NULL, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_semesters PRIMARY KEY (id), 
	CONSTRAINT uq_semesters_batch_id_number UNIQUE (batch_id, number), 
	CONSTRAINT ck_semesters_number_range CHECK (number BETWEEN 1 AND 12), 
	CONSTRAINT fk_semesters_batch_id_batches FOREIGN KEY(batch_id) REFERENCES batches (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_semesters_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT
);
CREATE INDEX ix_semesters_batch_id ON semesters (batch_id);
CREATE INDEX ix_semesters_department_id ON semesters (department_id);

CREATE TABLE sections (
	id SERIAL NOT NULL, 
	semester_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	name VARCHAR(20) NOT NULL, 
	capacity INTEGER, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_sections PRIMARY KEY (id), 
	CONSTRAINT uq_sections_semester_id_name UNIQUE (semester_id, name), 
	CONSTRAINT fk_sections_semester_id_semesters FOREIGN KEY(semester_id) REFERENCES semesters (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_sections_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT
);
CREATE INDEX ix_sections_department_id ON sections (department_id);
CREATE INDEX ix_sections_semester_id ON sections (semester_id);

CREATE TABLE students (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	batch_id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	section_id INTEGER NOT NULL, 
	registration_no VARCHAR(50) NOT NULL, 
	profile_photo_path VARCHAR(500), 
	profile_photo_updated_at TIMESTAMP WITH TIME ZONE, 
	face_enrollment_status VARCHAR(32) DEFAULT 'not_started' NOT NULL, 
	face_submitted_at TIMESTAMP WITH TIME ZONE, 
	face_reviewed_at TIMESTAMP WITH TIME ZONE, 
	face_reviewed_by_id INTEGER, 
	face_review_note TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_students PRIMARY KEY (id), 
	CONSTRAINT uq_students_user_id UNIQUE (user_id), 
	CONSTRAINT fk_students_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_students_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_students_batch_id_batches FOREIGN KEY(batch_id) REFERENCES batches (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_students_semester_id_semesters FOREIGN KEY(semester_id) REFERENCES semesters (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_students_section_id_sections FOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE RESTRICT, 
	CONSTRAINT ck_students_face_enrollment_status CHECK (face_enrollment_status IN ('not_started', 'incomplete', 'pending_review', 'approved', 'rejected')), 
	CONSTRAINT fk_students_face_reviewed_by_id_users FOREIGN KEY(face_reviewed_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_students_batch_id ON students (batch_id);
CREATE INDEX ix_students_department_id ON students (department_id);
CREATE INDEX ix_students_face_enrollment_status ON students (face_enrollment_status);
CREATE UNIQUE INDEX ix_students_registration_no ON students (registration_no);
CREATE INDEX ix_students_section_id ON students (section_id);
CREATE INDEX ix_students_semester_id ON students (semester_id);

CREATE TABLE teacher_course_assignments (
	id SERIAL NOT NULL, 
	teacher_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	section_id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	assigned_by_id INTEGER, 
	assigned_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_teacher_course_assignments PRIMARY KEY (id), 
	CONSTRAINT uq_teacher_course_assignments_teacher_id_course_id_section_id UNIQUE (teacher_id, course_id, section_id), 
	CONSTRAINT fk_teacher_course_assignments_teacher_id_teachers FOREIGN KEY(teacher_id) REFERENCES teachers (id) ON DELETE CASCADE, 
	CONSTRAINT fk_teacher_course_assignments_course_id_courses FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_teacher_course_assignments_section_id_sections FOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_teacher_course_assignments_semester_id_semesters FOREIGN KEY(semester_id) REFERENCES semesters (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_teacher_course_assignments_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_teacher_course_assignments_assigned_by_id_users FOREIGN KEY(assigned_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_teacher_course_assignments_course_id ON teacher_course_assignments (course_id);
CREATE INDEX ix_teacher_course_assignments_department_id ON teacher_course_assignments (department_id);
CREATE INDEX ix_teacher_course_assignments_section_id ON teacher_course_assignments (section_id);
CREATE INDEX ix_teacher_course_assignments_teacher_id ON teacher_course_assignments (teacher_id);

CREATE TABLE attendance_sessions (
	id SERIAL NOT NULL, 
	assignment_id INTEGER, 
	teacher_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	section_id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	session_date DATE NOT NULL, 
	session_number SMALLINT NOT NULL, 
	start_time TIME WITHOUT TIME ZONE, 
	status VARCHAR(32) NOT NULL, 
	note VARCHAR(300), 
	faces_detected INTEGER, 
	version INTEGER DEFAULT '1' NOT NULL, 
	finalized_at TIMESTAMP WITH TIME ZONE, 
	finalized_by_id INTEGER, 
	cancelled_at TIMESTAMP WITH TIME ZONE, 
	cancelled_by_id INTEGER, 
	cancel_reason VARCHAR(300), 
	created_by_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_attendance_sessions PRIMARY KEY (id), 
	CONSTRAINT ck_attendance_sessions_session_number_positive CHECK (session_number >= 1), 
	CONSTRAINT ck_attendance_sessions_version_positive CHECK (version >= 1), 
	CONSTRAINT fk_attendance_sessions_assignment_id_teacher_course_assignments FOREIGN KEY(assignment_id) REFERENCES teacher_course_assignments (id) ON DELETE SET NULL, 
	CONSTRAINT fk_attendance_sessions_teacher_id_teachers FOREIGN KEY(teacher_id) REFERENCES teachers (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_sessions_course_id_courses FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_sessions_section_id_sections FOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_sessions_semester_id_semesters FOREIGN KEY(semester_id) REFERENCES semesters (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_sessions_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, 
	CONSTRAINT ck_attendance_sessions_session_status CHECK (status IN ('draft', 'finalized', 'cancelled')), 
	CONSTRAINT fk_attendance_sessions_finalized_by_id_users FOREIGN KEY(finalized_by_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_attendance_sessions_cancelled_by_id_users FOREIGN KEY(cancelled_by_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_attendance_sessions_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE RESTRICT
);
CREATE INDEX ix_attendance_sessions_course_id ON attendance_sessions (course_id);
CREATE INDEX ix_attendance_sessions_department_id ON attendance_sessions (department_id);
CREATE INDEX ix_attendance_sessions_section_id ON attendance_sessions (section_id);
CREATE INDEX ix_attendance_sessions_session_date ON attendance_sessions (session_date);
CREATE INDEX ix_attendance_sessions_status ON attendance_sessions (status);
CREATE INDEX ix_attendance_sessions_teacher_id ON attendance_sessions (teacher_id);
CREATE UNIQUE INDEX uq_attendance_sessions_active_slot ON attendance_sessions (course_id, section_id, session_date, session_number) WHERE status <> 'cancelled';

CREATE TABLE student_course_enrollments (
	id SERIAL NOT NULL, 
	student_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	section_id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_student_course_enrollments PRIMARY KEY (id), 
	CONSTRAINT uq_student_course_enrollments_student_id_course_id_semester_id UNIQUE (student_id, course_id, semester_id), 
	CONSTRAINT fk_student_course_enrollments_student_id_students FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE CASCADE, 
	CONSTRAINT fk_student_course_enrollments_course_id_courses FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_student_course_enrollments_section_id_sections FOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_student_course_enrollments_semester_id_semesters FOREIGN KEY(semester_id) REFERENCES semesters (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_student_course_enrollments_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT
);
CREATE INDEX ix_student_course_enrollments_course_id ON student_course_enrollments (course_id);
CREATE INDEX ix_student_course_enrollments_department_id ON student_course_enrollments (department_id);
CREATE INDEX ix_student_course_enrollments_section_id ON student_course_enrollments (section_id);
CREATE INDEX ix_student_course_enrollments_student_id ON student_course_enrollments (student_id);

CREATE TABLE student_face_images (
	id SERIAL NOT NULL, 
	student_id INTEGER NOT NULL, 
	image_path VARCHAR(500) NOT NULL, 
	image_type VARCHAR(32) NOT NULL, 
	is_usable BOOLEAN NOT NULL, 
	validation_status VARCHAR(32) DEFAULT 'pass' NOT NULL, 
	validation_message TEXT, 
	quality JSONB, 
	width INTEGER, 
	height INTEGER, 
	file_size INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	reviewed_by_id INTEGER, 
	CONSTRAINT pk_student_face_images PRIMARY KEY (id), 
	CONSTRAINT fk_student_face_images_student_id_students FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE CASCADE, 
	CONSTRAINT ck_student_face_images_face_image_type CHECK (image_type IN ('front', 'left', 'right', 'extra')), 
	CONSTRAINT ck_student_face_images_image_check_status CHECK (validation_status IN ('pass', 'warning', 'fail')), 
	CONSTRAINT fk_student_face_images_reviewed_by_id_users FOREIGN KEY(reviewed_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_student_face_images_student_id ON student_face_images (student_id);

CREATE TABLE attendance_recognition_runs (
	id SERIAL NOT NULL, 
	session_id INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	started_by_id INTEGER, 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	model_name VARCHAR(100) NOT NULL, 
	model_version VARCHAR(100) NOT NULL, 
	thresholds JSONB, 
	image_count INTEGER NOT NULL, 
	faces_detected INTEGER NOT NULL, 
	confident_count INTEGER NOT NULL, 
	low_confidence_count INTEGER NOT NULL, 
	ambiguous_count INTEGER NOT NULL, 
	duplicate_count INTEGER NOT NULL, 
	unknown_count INTEGER NOT NULL, 
	students_recognized INTEGER NOT NULL, 
	roster_size INTEGER NOT NULL, 
	eligible_count INTEGER NOT NULL, 
	applied_count INTEGER NOT NULL, 
	preserved_count INTEGER NOT NULL, 
	missing_student_ids JSONB, 
	warnings JSONB, 
	error_message VARCHAR(300), 
	CONSTRAINT pk_attendance_recognition_runs PRIMARY KEY (id), 
	CONSTRAINT fk_attendance_recognition_runs_session_id_attendance_sessions FOREIGN KEY(session_id) REFERENCES attendance_sessions (id) ON DELETE CASCADE, 
	CONSTRAINT ck_attendance_recognition_runs_recognition_run_status CHECK (status IN ('processing', 'completed', 'completed_with_warnings', 'failed')), 
	CONSTRAINT fk_attendance_recognition_runs_started_by_id_users FOREIGN KEY(started_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_attendance_recognition_runs_session_id ON attendance_recognition_runs (session_id);

CREATE TABLE attendance_session_images (
	id SERIAL NOT NULL, 
	session_id INTEGER NOT NULL, 
	image_path VARCHAR(500) NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	file_size INTEGER NOT NULL, 
	uploaded_by_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_attendance_session_images PRIMARY KEY (id), 
	CONSTRAINT fk_attendance_session_images_session_id_attendance_sessions FOREIGN KEY(session_id) REFERENCES attendance_sessions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_attendance_session_images_uploaded_by_id_users FOREIGN KEY(uploaded_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_attendance_session_images_session_id ON attendance_session_images (session_id);

CREATE TABLE face_embeddings (
	id SERIAL NOT NULL, 
	student_id INTEGER NOT NULL, 
	face_image_id INTEGER NOT NULL, 
	embedding_vector BYTEA NOT NULL, 
	dimension INTEGER NOT NULL, 
	model_name VARCHAR(100) NOT NULL, 
	model_version VARCHAR(100) DEFAULT '' NOT NULL, 
	source_updated_at TIMESTAMP WITH TIME ZONE, 
	det_score FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_face_embeddings PRIMARY KEY (id), 
	CONSTRAINT fk_face_embeddings_student_id_students FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE CASCADE, 
	CONSTRAINT uq_face_embeddings_face_image_id UNIQUE (face_image_id), 
	CONSTRAINT fk_face_embeddings_face_image_id_student_face_images FOREIGN KEY(face_image_id) REFERENCES student_face_images (id) ON DELETE CASCADE
);
CREATE INDEX ix_face_embeddings_student_id ON face_embeddings (student_id);

CREATE TABLE attendance_recognition_faces (
	id SERIAL NOT NULL, 
	run_id INTEGER NOT NULL, 
	image_id INTEGER NOT NULL, 
	face_index INTEGER NOT NULL, 
	bbox_x INTEGER NOT NULL, 
	bbox_y INTEGER NOT NULL, 
	bbox_w INTEGER NOT NULL, 
	bbox_h INTEGER NOT NULL, 
	det_score FLOAT NOT NULL, 
	category VARCHAR(32) NOT NULL, 
	student_id INTEGER, 
	similarity FLOAT, 
	second_student_id INTEGER, 
	second_similarity FLOAT, 
	is_primary BOOLEAN NOT NULL, 
	decision VARCHAR(32) NOT NULL, 
	assigned_student_id INTEGER, 
	decided_by_id INTEGER, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_attendance_recognition_faces PRIMARY KEY (id), 
	CONSTRAINT fk_attendance_recognition_faces_run_id_attendance_recog_60e2 FOREIGN KEY(run_id) REFERENCES attendance_recognition_runs (id) ON DELETE CASCADE, 
	CONSTRAINT fk_attendance_recognition_faces_image_id_attendance_ses_47d9 FOREIGN KEY(image_id) REFERENCES attendance_session_images (id) ON DELETE CASCADE, 
	CONSTRAINT ck_attendance_recognition_faces_recognition_category CHECK (category IN ('confident', 'low_confidence', 'ambiguous', 'duplicate', 'no_match')), 
	CONSTRAINT fk_attendance_recognition_faces_student_id_students FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE SET NULL, 
	CONSTRAINT fk_attendance_recognition_faces_second_student_id_students FOREIGN KEY(second_student_id) REFERENCES students (id) ON DELETE SET NULL, 
	CONSTRAINT ck_attendance_recognition_faces_face_decision CHECK (decision IN ('applied', 'manual_kept', 'pending', 'accepted', 'assigned', 'rejected', 'none')), 
	CONSTRAINT fk_attendance_recognition_faces_assigned_student_id_students FOREIGN KEY(assigned_student_id) REFERENCES students (id) ON DELETE SET NULL, 
	CONSTRAINT fk_attendance_recognition_faces_decided_by_id_users FOREIGN KEY(decided_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_attendance_recognition_faces_image_id ON attendance_recognition_faces (image_id);
CREATE INDEX ix_attendance_recognition_faces_run_id ON attendance_recognition_faces (run_id);

CREATE TABLE attendance_records (
	id SERIAL NOT NULL, 
	session_id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	teacher_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	department_id INTEGER NOT NULL, 
	semester_id INTEGER NOT NULL, 
	section_id INTEGER NOT NULL, 
	attendance_date DATE NOT NULL, 
	attendance_time TIME WITHOUT TIME ZONE, 
	session_number SMALLINT NOT NULL, 
	status VARCHAR(32), 
	note VARCHAR(200), 
	confidence FLOAT, 
	method VARCHAR(32) NOT NULL, 
	created_by_id INTEGER NOT NULL, 
	last_modified_by_id INTEGER, 
	recognition_run_id INTEGER, 
	recognition_face_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_attendance_records PRIMARY KEY (id), 
	CONSTRAINT uq_attendance_records_session_id_student_id UNIQUE (session_id, student_id), 
	CONSTRAINT ck_attendance_records_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
	CONSTRAINT fk_attendance_records_session_id_attendance_sessions FOREIGN KEY(session_id) REFERENCES attendance_sessions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_attendance_records_student_id_students FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_records_teacher_id_teachers FOREIGN KEY(teacher_id) REFERENCES teachers (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_records_course_id_courses FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_records_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_records_semester_id_semesters FOREIGN KEY(semester_id) REFERENCES semesters (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_records_section_id_sections FOREIGN KEY(section_id) REFERENCES sections (id) ON DELETE RESTRICT, 
	CONSTRAINT ck_attendance_records_attendance_status CHECK (status IN ('present', 'absent', 'late', 'excused')), 
	CONSTRAINT ck_attendance_records_attendance_method CHECK (method IN ('face_recognition', 'face_recognition_confirmed', 'manual', 'hod_override')), 
	CONSTRAINT fk_attendance_records_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_attendance_records_last_modified_by_id_users FOREIGN KEY(last_modified_by_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_attendance_records_recognition_run_id_attendance_rec_349f FOREIGN KEY(recognition_run_id) REFERENCES attendance_recognition_runs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_attendance_records_recognition_face_id_attendance_re_bc45 FOREIGN KEY(recognition_face_id) REFERENCES attendance_recognition_faces (id) ON DELETE SET NULL
);
CREATE INDEX ix_attendance_records_attendance_date ON attendance_records (attendance_date);
CREATE INDEX ix_attendance_records_course_id ON attendance_records (course_id);
CREATE INDEX ix_attendance_records_department_id ON attendance_records (department_id);
CREATE INDEX ix_attendance_records_session_id ON attendance_records (session_id);
CREATE INDEX ix_attendance_records_status ON attendance_records (status);
CREATE INDEX ix_attendance_records_student_id ON attendance_records (student_id);
CREATE INDEX ix_attendance_records_teacher_id ON attendance_records (teacher_id);

CREATE TABLE attendance_modifications (
	id SERIAL NOT NULL, 
	record_id INTEGER NOT NULL, 
	modified_by_id INTEGER NOT NULL, 
	modifier_role VARCHAR(32) NOT NULL, 
	old_value JSONB NOT NULL, 
	new_value JSONB NOT NULL, 
	reason TEXT NOT NULL, 
	modified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_attendance_modifications PRIMARY KEY (id), 
	CONSTRAINT fk_attendance_modifications_record_id_attendance_records FOREIGN KEY(record_id) REFERENCES attendance_records (id) ON DELETE CASCADE, 
	CONSTRAINT fk_attendance_modifications_modified_by_id_users FOREIGN KEY(modified_by_id) REFERENCES users (id) ON DELETE RESTRICT, 
	CONSTRAINT ck_attendance_modifications_user_role CHECK (modifier_role IN ('super_admin', 'hod', 'teacher', 'student'))
);
CREATE INDEX ix_attendance_modifications_record_id ON attendance_modifications (record_id);

