"""Phase 10: IDOR matrix — every ID-bearing endpoint called directly with someone else's IDs.

Owner: the CSE teacher (session with a classroom photo, a recognition run, a finalized-able
roster). Attackers: an EE teacher (other department), an unassigned CSE teacher, the EE HOD,
the CSE HOD, a CSE student and the EE student. Every call must be refused with the established
403/404 (never 200/201/204), and nothing may change.
"""

import pytest
from sqlalchemy import select

from backend.app.models import (
    AttendanceRecognitionFace,
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionImage,
    StudentCourseEnrollment,
    StudentFaceImage,
)
from tests.conftest import STUDENT_EMAIL
from tests.fake_face_engine import random_identity, with_similarity
from tests.test_attendance import ee_class  # noqa: F401
from tests.test_recognition import classroom_photo, rc, run, teacher_h  # noqa: F401

API = "/api/v1"
DENIED = {401, 403, 404}


@pytest.fixture()
def world(client, teacher_h, rc, fake_face_engine, ee_class, hod_h, login, db_session):  # noqa: F811
    s = rc["session"]
    classroom_photo(client, teacher_h, s["id"], fake_face_engine, 900, 600,
                    [with_similarity(rc["vec"]["F23CSE01"], 0.42), random_identity(3)])
    s = client.get(f"{API}/attendance/sessions/{s['id']}", headers=teacher_h).json()
    body = run(client, teacher_h, s).json()
    client.post(f"{API}/teachers", headers=hod_h, json={"full_name": "Idle T", "email": "idle@test.edu",
                                                     "password": "Teach@1234", "employee_id": "EMP-T-555"})
    with db_session() as db:
        enrollment = db.scalar(select(StudentCourseEnrollment.id).where(
            StudentCourseEnrollment.course_id == db.get(AttendanceSession, s["id"]).course_id))
        face_photo = db.scalar(select(StudentFaceImage.id).where(StudentFaceImage.student_id == rc["sid"]["F23CSE01"]))
    return {
        "session": body["session"], "version": body["session"]["version"], "assignment": rc["assignment"],
        "record": body["session"]["records"][0]["id"], "image": body["session"]["images"][0]["id"],
        "face": body["recognition"]["faces"][0]["id"], "student": rc["sid"]["F23CSE01"], "enrollment": enrollment,
        "face_photo": face_photo, "course": body["session"]["course_id"], "ee": ee_class,
        "attackers": {
            "ee_teacher": ee_class["teacher_h"], "idle_cse_teacher": login("idle@test.edu", "Teach@1234"),
            "ee_hod": ee_class["hod_h"], "cse_hod": hod_h, "cse_student": login(STUDENT_EMAIL),
            "ee_student": login("student.ee@test.edu"), "anonymous": {},
        },
    }


def _attendance_calls(w):
    sid, v = w["session"]["id"], w["version"]
    return [
        ("get", f"/attendance/sessions/{sid}", None),
        ("patch", f"/attendance/sessions/{sid}", {"version": v, "note": "x"}),
        ("patch", f"/attendance/sessions/{sid}/records", {"version": v, "changes": [{"record_id": w["record"], "status": "absent"}]}),
        ("post", f"/attendance/sessions/{sid}/bulk", {"version": v, "action": "all_absent"}),
        ("post", f"/attendance/sessions/{sid}/finalize", {"version": v}),
        ("post", f"/attendance/sessions/{sid}/cancel", {"version": v}),
        ("post", f"/attendance/sessions/{sid}/delete", {"reason": "Wrong class entirely"}),
        ("delete", f"/attendance/sessions/{sid}/images/{w['image']}", None),
        ("get", f"/attendance/images/{w['image']}", None),
        ("post", f"/attendance/records/{w['record']}/correct", {"status": "absent", "reason": "Left early"}),
        ("get", f"/attendance/sessions/{sid}/recognition", None),
        ("post", f"/attendance/sessions/{sid}/recognition", {"version": v}),
        ("post", f"/attendance/recognition/faces/{w['face']}/accept", {"version": v}),
        ("post", f"/attendance/recognition/faces/{w['face']}/assign", {"version": v, "student_id": w["student"]}),
        ("post", f"/attendance/recognition/faces/{w['face']}/reject", {"version": v}),
        ("get", f"/reports/class/{w['assignment']}", None),
        ("get", f"/reports/class/{w['assignment']}/daily", {"date": w["session"]["session_date"]}),
        ("get", f"/reports/class/{w['assignment']}/monthly", {"year": 2026, "month": 10}),
        ("get", f"/reports/class/{w['assignment']}/students/{w['student']}", None),
        ("get", f"/reports/class/{w['assignment']}/export", None),
        ("get", "/enrollments", {"assignment_id": w["assignment"]}),
        ("get", "/enrollments/candidates", {"assignment_id": w["assignment"]}),
        ("delete", f"/enrollments/{w['enrollment']}", None),
        ("post", "/enrollments", {"assignment_id": w["assignment"], "student_id": w["student"]}),
        ("post", "/enrollments/bulk", {"assignment_id": w["assignment"]}),
    ]


def _call(client, headers, method, path, payload):
    kwargs = {"headers": headers}
    if payload is not None:
        kwargs["params" if method == "get" else "json"] = payload
    return getattr(client, method)(f"{API}{path}", **kwargs)


def _snapshot(db_session, w):
    with db_session() as db:
        s = db.get(AttendanceSession, w["session"]["id"])
        return (s.status, s.version, s.note,
                tuple(db.scalars(select(AttendanceRecord.status).where(AttendanceRecord.session_id == s.id)
                                 .order_by(AttendanceRecord.id))),
                db.scalar(select(AttendanceRecognitionFace.decision).where(AttendanceRecognitionFace.id == w["face"])),
                db.get(StudentCourseEnrollment, w["enrollment"]).is_active,
                db.scalar(select(AttendanceSessionImage.id).where(AttendanceSessionImage.id == w["image"])))


def test_nobody_else_can_touch_a_teachers_attendance_reports_or_enrollments(client, world, db_session):
    before = _snapshot(db_session, world)
    leaks = []
    for who, headers in world["attackers"].items():
        for method, path, payload in _attendance_calls(world):
            res = _call(client, headers, method, path, payload)
            if res.status_code not in DENIED:
                leaks.append((who, method, path, res.status_code))
            elif who.endswith("teacher") and "/attendance/" in path and res.status_code != 404:
                leaks.append((who, method, path, f"{res.status_code} (other teachers must get 404)"))
    assert leaks == []
    assert _snapshot(db_session, world) == before


def test_departments_and_people_are_isolated_by_id(client, world, ids, ee):
    cse = {"student": ids["student"], "teacher": ids["teacher"], "dept": ids["cse"],
           "batch": ids["batch"], "semester": ids["semester"], "section": ids["section_a"],
           "course": ids["courses"]["CS-321"]}
    ee_hod = world["attackers"]["ee_hod"]
    for path in (f"/students/{cse['student']}", f"/teachers/{cse['teacher']}", f"/batches/{cse['batch']}",
                 f"/semesters/{cse['semester']}", f"/sections/{cse['section']}", f"/courses/{cse['course']}",
                 f"/face-enrollments/{cse['student']}", f"/students/{cse['student']}/profile-photo",
                 f"/face-photos/{world['face_photo']}/image"):
        res = client.get(f"{API}{path}", headers=ee_hod)
        assert res.status_code in (403, 404), (path, res.status_code)
    for path, body in ((f"/students/{cse['student']}", {"full_name": "Hijacked"}),
                       (f"/courses/{cse['course']}", {"title": "Hijacked"}),
                       (f"/sections/{cse['section']}", {"name": "Z"})):
        assert client.patch(f"{API}{path}", headers=ee_hod, json=body).status_code in (403, 404), path
    assert client.post(f"{API}/face-enrollments/{cse['student']}/approve", headers=ee_hod).status_code in (403, 404)
    assert client.post(f"{API}/face-enrollments/{cse['student']}/reject", headers=ee_hod,
                       json={"reason": "Please retake all photos"}).status_code in (403, 404)
    with_assignment = client.get(f"{API}/assignments", headers=world["attackers"]["cse_hod"]).json()["items"][0]["id"]
    assert client.delete(f"{API}/assignments/{with_assignment}", headers=ee_hod).status_code in (403, 404)
    # HODs never see another department, even by guessing its id.
    assert client.get(f"{API}/departments/{cse['dept']}", headers=ee_hod).status_code in (403, 404)


def test_students_reach_only_their_own_data(client, world, ids):
    cse_student, ee_student = world["attackers"]["cse_student"], world["attackers"]["ee_student"]
    # Another student's photos and profile, by id.
    assert client.get(f"{API}/face-photos/{world['face_photo']}/image", headers=cse_student).status_code in (403, 404)
    assert client.get(f"{API}/students/{world['student']}/profile-photo", headers=ee_student).status_code in (403, 404)
    assert client.get(f"{API}/students/{world['student']}", headers=cse_student).status_code == 403
    assert client.put(f"{API}/me/face-photos/{world['face_photo']}", headers=cse_student,
                      files={"file": ("f.jpg", b"\xff\xd8", "image/jpeg")}).status_code in (403, 404, 409, 422)
    assert client.delete(f"{API}/me/face-photos/{world['face_photo']}", headers=cse_student).status_code in (403, 404, 409)
    # A subject the student is not enrolled in.
    assert client.get(f"{API}/student/attendance/subjects/{world['course']}", headers=ee_student).status_code == 404
    # Staff administration is not theirs.
    for path in (f"/accounts/{ids['teacher_user']}/status", f"/accounts/{ids['teacher_user']}/reset-password"):
        assert client.request("PATCH" if path.endswith("status") else "POST", f"{API}{path}", headers=cse_student,
                              json={"status": "suspended", "new_password": "Hacked@1234"}).status_code == 403


def test_super_admin_cannot_reach_attendance_or_recognition_by_id(client, world, admin_h):
    leaks = [(m, p, r.status_code) for m, p, b in _attendance_calls(world)
             if (r := _call(client, admin_h, m, p, b)).status_code not in (403, 404)]
    assert leaks == []
