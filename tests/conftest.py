"""Test fixtures: in-memory SQLite database seeded with the demo dataset.

Models use portable column types, so the suite runs without PostgreSQL.
"""

import os

# Must be set before the app (and its settings) are imported.
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["FACE_RECOGNITION_PRELOAD"] = "false"  # tests use a fake engine; never load real models at startup

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.app.auth.rate_limit import login_rate_limiter  # noqa: E402
from backend.app.auth.security import hash_password  # noqa: E402
from backend.app.database.base import Base  # noqa: E402
from backend.app.database.session import get_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import AccountStatus, User, UserRole  # noqa: E402
from backend.app.scripts.seed_demo import DEMO_PASSWORD, seed  # noqa: E402

ADMIN_EMAIL = "admin@test.edu"


# Run the whole suite against PostgreSQL instead of in-memory SQLite:
#   $env:SMARTCLASS_TEST_DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@localhost:5432/smartclass_phase10_test"
# The database is WIPED before every test, so its name must contain "test" (never a real database).
TEST_DATABASE_URL = os.environ.get("SMARTCLASS_TEST_DATABASE_URL", "")
if TEST_DATABASE_URL and "test" not in TEST_DATABASE_URL.rsplit("/", 1)[-1]:
    raise RuntimeError("SMARTCLASS_TEST_DATABASE_URL must name a dedicated *test* database (it is wiped per test).")
ON_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")


def make_test_engine():
    """A fresh, empty schema: PostgreSQL (real connection pool) when configured, else SQLite in memory."""
    if ON_POSTGRES:
        from sqlalchemy import text

        engine = create_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=10)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        return engine
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture()
def db_session():
    engine = make_test_engine()
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TestingSession() as session:
        session.add(User(email=ADMIN_EMAIL, full_name="Admin", role=UserRole.SUPER_ADMIN,
                         status=AccountStatus.ACTIVE, password_hash=hash_password(DEMO_PASSWORD)))
        seed(session)
    yield TestingSession
    engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        with db_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    login_rate_limiter.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def login(client):
    """login("hod.cse@smartclass.edu") -> auth headers"""

    def _login(email: str, password: str = DEMO_PASSWORD) -> dict[str, str]:
        res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text
        return {"Authorization": f"Bearer {res.json()['access_token']}"}

    return _login


HOD_EMAIL = "hod.cse@smartclass.edu"
TEACHER_EMAIL = "teacher.cse@smartclass.edu"
STUDENT_EMAIL = "student.cse@smartclass.edu"


@pytest.fixture()
def admin_h(login):
    return login(ADMIN_EMAIL)


@pytest.fixture()
def hod_h(login):
    return login(HOD_EMAIL)


@pytest.fixture()
def ids(db_session):
    """Primary keys of the seeded CSE data."""
    from sqlalchemy import select

    from backend.app.models import Batch, Course, Department, Section, Semester, Student, Teacher

    with db_session() as db:
        cse = db.scalar(select(Department).where(Department.code == "CSE"))
        ee = db.scalar(select(Department).where(Department.code == "EE"))
        batch = db.scalar(select(Batch).where(Batch.department_id == cse.id))
        sem = db.scalar(select(Semester).where(Semester.batch_id == batch.id))
        sections = {s.name: s.id for s in db.scalars(select(Section).where(Section.semester_id == sem.id))}
        courses = {c.code: c.id for c in db.scalars(select(Course).where(Course.department_id == cse.id))}
        teacher = db.scalar(select(Teacher).where(Teacher.employee_id == "EMP-T-101"))
        student = db.scalar(select(Student).where(Student.registration_no == "F23CSE01"))
        pending = db.scalar(select(Student).where(Student.registration_no == "F23CSE03"))
        return {
            "cse": cse.id, "ee": ee.id, "batch": batch.id, "semester": sem.id, "section_a": sections["A"],
            "section_b": sections["B"], "courses": courses, "teacher": teacher.id, "teacher_user": teacher.user_id,
            "student": student.id, "student_user": student.user_id, "pending": pending.id,
            "pending_user": pending.user_id,
        }


@pytest.fixture()
def ee(db_session):
    """A fully populated second department (EE) for cross-department isolation tests."""
    from sqlalchemy import select

    from backend.app.models import Batch, Course, Department, Section, Semester, Student, Teacher

    with db_session() as db:
        dept = db.scalar(select(Department).where(Department.code == "EE"))
        batch = Batch(department_id=dept.id, name="F24", start_year=2024)
        db.add(batch)
        db.flush()
        sem = Semester(batch_id=batch.id, department_id=dept.id, number=2)
        db.add(sem)
        db.flush()
        section = Section(semester_id=sem.id, department_id=dept.id, name="A")
        course = Course(department_id=dept.id, code="EE-101", title="Circuit Analysis")
        db.add_all([section, course])
        db.flush()
        t_user = User(email="teacher.ee@test.edu", full_name="EE Teacher", role=UserRole.TEACHER,
                      status=AccountStatus.ACTIVE, password_hash=hash_password(DEMO_PASSWORD))
        t_user.teacher_profile = Teacher(department_id=dept.id, employee_id="EMP-EE-1")
        s_user = User(email="student.ee@test.edu", full_name="EE Student", role=UserRole.STUDENT,
                      status=AccountStatus.ACTIVE, password_hash=hash_password(DEMO_PASSWORD))
        s_user.student_profile = Student(department_id=dept.id, batch_id=batch.id, semester_id=sem.id,
                                         section_id=section.id, registration_no="F24EE01")
        db.add_all([t_user, s_user])
        db.commit()
        return {
            "dept": dept.id, "batch": batch.id, "semester": sem.id, "section": section.id, "course": course.id,
            "teacher": t_user.teacher_profile.id, "teacher_user": t_user.id,
            "student": s_user.student_profile.id, "student_user": s_user.id,
        }


@pytest.fixture()
def ee_hod_h(client, admin_h, ee, login):
    """Auth headers of a HOD for the EE department (the super admin creates the account; the
    HOD then does the department's academic and student work)."""
    res = client.post("/api/v1/hods", headers=admin_h, json={
        "full_name": "EE Head", "email": "hod.ee@test.edu", "password": "HodPass@123",
        "employee_id": "EMP-HOD-EE9", "department_id": ee["dept"]})
    assert res.status_code == 201, res.text
    return login("hod.ee@test.edu", "HodPass@123")


@pytest.fixture()
def audit(db_session):
    """audit("teacher.created") -> list of matching AuditLog rows (newest first)."""
    from sqlalchemy import select

    from backend.app.models import AuditLog

    def _find(action: str):
        with db_session() as db:
            return db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc())).all()

    return _find


from backend.app.core import config as _config_module  # noqa: E402

_SETTINGS = _config_module.settings
_REAL_UPLOADS = _config_module.PROJECT_ROOT / "uploads"


def _real_upload_files() -> set[str]:
    return {str(p) for p in _REAL_UPLOADS.rglob("*") if p.is_file()} if _REAL_UPLOADS.exists() else set()


@pytest.fixture(scope="session", autouse=True)
def real_uploads_untouched():
    """Safety net: no test may ever add files to the project's real uploads/ folder."""
    before = _real_upload_files()
    yield
    added = _real_upload_files() - before
    assert not added, f"tests wrote {len(added)} file(s) into the real uploads/ folder"


@pytest.fixture(autouse=True)
def settings_object_is_never_replaced():
    """Every module shares ONE settings object; fixtures below patch it (e.g. UPLOAD_DIR). If a test
    replaced it (e.g. by reloading the config module), later patches would miss the running app
    and tests could touch real data — so stop the run at once."""
    assert _config_module.settings is _SETTINGS, "backend.app.core.config.settings was replaced"
    yield
    assert _config_module.settings is _SETTINGS, "a test replaced backend.app.core.config.settings"


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    """Every test writes uploads into its own temp dir — never into the real uploads/."""
    from backend.app.core.config import settings

    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(settings, "UPLOAD_DIR", upload_dir)
    return upload_dir


@pytest.fixture(autouse=True)
def fake_face_engine():
    """Every test uses a deterministic fake recognition engine — never the real model, never
    the network, never real faces."""
    from backend.app.face_recognition import model as face_model
    from tests.fake_face_engine import FakeEngine

    engine = FakeEngine()
    face_model.set_engine(engine)
    yield engine
    face_model.set_engine(None)
