import pytest
from sqlalchemy import select

from backend.app.models import Department, Section, User
from backend.app.scripts.seed_demo import DEMO_PASSWORD
from tests.conftest import ADMIN_EMAIL

API = "/api/v1"


@pytest.mark.parametrize(
    ("email", "role"),
    [
        (ADMIN_EMAIL, "super_admin"),
        ("hod.cse@smartclass.edu", "hod"),
        ("teacher.cse@smartclass.edu", "teacher"),
        ("student.cse@smartclass.edu", "student"),
    ],
)
def test_login_each_role(client, email, role):
    res = client.post(f"{API}/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["role"] == role
    assert body["access_token"] and body["refresh_token"] is None  # refresh token: HttpOnly cookie only
    assert res.cookies.get("sc_refresh")


def test_password_is_hashed(db_session):
    with db_session() as db:
        user = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert user.password_hash != DEMO_PASSWORD
        assert user.password_hash.startswith("$2")


def test_wrong_password_and_unknown_email_look_identical(client):
    a = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "Wrong@1234"})
    b = client.post(f"{API}/auth/login", json={"email": "nobody@test.edu", "password": "Wrong@1234"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_pending_student_cannot_login(client):
    res = client.post(f"{API}/auth/login", json={"email": "pending.cse@smartclass.edu", "password": DEMO_PASSWORD})
    assert res.status_code == 403
    assert "awaiting approval" in res.json()["detail"]


def test_login_rate_limit(client):
    payload = {"email": ADMIN_EMAIL, "password": "Wrong@1234"}
    for _ in range(5):
        assert client.post(f"{API}/auth/login", json=payload).status_code == 401
    res = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD})
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_me_requires_token(client, login):
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    res = client.get(f"{API}/auth/me", headers=login("teacher.cse@smartclass.edu"))
    assert res.status_code == 200
    assert res.json()["employee_id"] == "EMP-T-101"
    assert res.json()["department_name"] == "Computer Systems Engineering"


def test_refresh_token_flow(client):
    tokens = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}).json()
    refresh_cookie = client.cookies.get("sc_refresh")
    client.cookies.clear()
    # An access token must not be usable as a refresh token.
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    client.cookies.set("sc_refresh", refresh_cookie, path="/api/v1/auth")
    res = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "SmartClass"})
    assert res.status_code == 200 and res.json()["access_token"]


def test_password_change_revokes_old_tokens(client, login):
    headers = login("teacher.cse@smartclass.edu")
    res = client.post(f"{API}/auth/change-password", headers=headers,
                      json={"current_password": DEMO_PASSWORD, "new_password": "NewPass@2026"})
    assert res.status_code == 200
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401
    login("teacher.cse@smartclass.edu", "NewPass@2026")


def _registration(db_session, **overrides):
    with db_session() as db:
        section = db.scalar(select(Section).where(Section.name == "A"))
        semester = section.semester
        payload = {
            "full_name": "  Hassan   Ali ",
            "registration_no": "f23cse04",
            "email": "Hassan@Test.edu",
            "password": "Student@123",
            "department_id": section.department_id,
            "batch_id": semester.batch_id,
            "semester_id": semester.id,
            "section_id": section.id,
        }
    payload.update(overrides)
    return payload


def test_student_registration_is_pending(client, db_session):
    res = client.post(f"{API}/auth/register/student", json=_registration(db_session))
    assert res.status_code == 201
    with db_session() as db:
        user = db.scalar(select(User).where(User.email == "hassan@test.edu"))
        assert user.status.value == "pending"
        assert user.full_name == "Hassan Ali"
        assert user.student_profile.registration_no == "F23CSE04"
    # Duplicate registration number is rejected.
    dup = client.post(f"{API}/auth/register/student", json=_registration(db_session, email="other@test.edu"))
    assert dup.status_code == 409


def test_registration_rejects_mismatched_structure(client, db_session):
    """A CSE batch/semester/section submitted under the EE department must be refused."""
    with db_session() as db:
        ee_id = db.scalar(select(Department.id).where(Department.code == "EE"))
    res = client.post(f"{API}/auth/register/student", json=_registration(db_session, department_id=ee_id))
    assert res.status_code == 422


def test_registration_rejects_weak_password(client, db_session):
    res = client.post(f"{API}/auth/register/student", json=_registration(db_session, password="weakpass"))
    assert res.status_code == 422
