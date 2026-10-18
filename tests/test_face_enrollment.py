"""Profile photos, face enrollment, review workflow, image authorisation and audit (Phase 4)."""

import json

import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.models import AuditLog, Student, StudentFaceImage
from tests import imaging
from tests.conftest import STUDENT_EMAIL, TEACHER_EMAIL

API = "/api/v1"


def upload(client, headers, pose, img=None, data=None, content_type="image/png", photo_id=None):
    files = {"file": ("selfie.png", data if data is not None else imaging.png(img if img is not None else imaging.face()),
                      content_type)}
    if photo_id is not None:
        return client.put(f"{API}/me/face-photos/{photo_id}", files=files, headers=headers)
    return client.post(f"{API}/me/face-photos", data={"pose": pose}, files=files, headers=headers)


def upload_all_required(client, headers):
    return {pose: upload(client, headers, pose, imaging.face(turn=turn)).json()
            for pose, turn in (("front", 0), ("left", -30), ("right", 30))}


def put_profile(client, headers, img=None, data=None, content_type="image/png"):
    files = {"file": ("me.png", data if data is not None else imaging.png(img if img is not None else imaging.face()),
                      content_type)}
    return client.put(f"{API}/me/profile-photo", files=files, headers=headers)


@pytest.fixture()
def student_h(login):
    return login(STUDENT_EMAIL)


@pytest.fixture()
def other_student_h(client, hod_h, ids, login):
    """A second approved CSE student."""
    client.post(f"{API}/students", headers=hod_h, json={
        "full_name": "Other Student", "email": "other@test.edu", "password": "Student@123",
        "registration_no": "F23CSE09", "batch_id": ids["batch"], "semester_id": ids["semester"],
        "section_id": ids["section_a"]})
    return login("other@test.edu", "Student@123")


def files_on_disk(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.jpg")) if root.exists() else []


# ── Profile photo ─────────────────────────────────────────────────────────


def test_profile_upload_replace_and_retrieve(client, student_h, ids, isolated_uploads, audit):
    res = put_profile(client, student_h)
    assert res.status_code == 200, res.text
    first_url = res.json()["profile_photo_url"]
    assert first_url.startswith(f"/students/{ids['student']}/profile-photo")
    first_files = files_on_disk(isolated_uploads)
    assert len(first_files) == 1 and first_files[0].startswith(f"profiles/{ids['student']}/")
    assert "selfie" not in first_files[0] and "me.png" not in first_files[0]  # never the user's filename

    image = client.get(f"{API}{first_url}", headers=student_h)
    assert image.status_code == 200 and image.content[:2] == b"\xff\xd8"
    assert image.headers["content-type"] == "image/jpeg"
    assert "no-store" in image.headers["cache-control"] and image.headers["x-content-type-options"] == "nosniff"

    assert put_profile(client, student_h, imaging.no_face()).status_code == 200  # profile needs no face
    files = files_on_disk(isolated_uploads)
    assert len(files) == 1 and files != first_files  # old file removed only after the new one is saved
    assert audit("profile_photo.uploaded") and audit("profile_photo.replaced")


@pytest.mark.parametrize("data,ctype,code", [
    (imaging.gif_bytes(), "image/gif", 415),
    (b"%PDF-1.7 not an image", "application/pdf", 415),
    (b"\xff\xd8\xff garbage", "image/jpeg", 422),
    (imaging.png(imaging.face(120)), "image/png", 422),
], ids=["gif", "pdf", "corrupt-jpeg", "too-small"])
def test_profile_upload_rejections(client, student_h, isolated_uploads, data, ctype, code):
    assert put_profile(client, student_h, data=data, content_type=ctype).status_code == code
    assert files_on_disk(isolated_uploads) == []


# ── Face photos ───────────────────────────────────────────────────────────


def test_face_upload_and_status(client, student_h, ids, isolated_uploads):
    status = client.get(f"{API}/me/face-enrollment", headers=student_h).json()
    assert status["status"] == "not_started" and status["missing_poses"] == ["front", "left", "right"]

    res = upload(client, student_h, "front")
    assert res.status_code == 201, res.text
    photo = res.json()
    assert photo["pose"] == "front" and photo["validation_status"] == "pass" and photo["width"] == 640
    assert photo["image_url"].startswith(f"/face-photos/{photo['id']}/image")
    assert "uploads" not in json.dumps(photo) and "faces/" not in json.dumps(photo)  # no filesystem paths

    status = client.get(f"{API}/me/face-enrollment", headers=student_h).json()
    assert status["status"] == "incomplete" and status["missing_poses"] == ["left", "right"]
    assert status["can_submit"] is False
    assert files_on_disk(isolated_uploads)[0].startswith(f"faces/{ids['student']}/")


@pytest.mark.parametrize("img,message", [
    (imaging.no_face(), "No face detected"),
    (imaging.two_faces(), "Multiple faces detected"),
    (imaging.blurred(), "too blurry"),
    (imaging.face(150), "too small"),
], ids=["no-face", "two-faces", "blurry", "too-small"])
def test_invalid_face_photos_are_refused_and_not_stored(client, student_h, db_session, isolated_uploads, img, message):
    res = upload(client, student_h, "front", img)
    assert res.status_code == 422 and message in res.json()["detail"]
    assert files_on_disk(isolated_uploads) == []
    with db_session() as db:
        assert db.scalar(select(StudentFaceImage.id)) is None


def test_invalid_pose_value(client, student_h):
    assert upload(client, student_h, "upside_down").status_code == 422


def test_duplicate_required_pose_and_max_five(client, student_h):
    upload_all_required(client, student_h)
    dup = upload(client, student_h, "front", imaging.face(seed=11))
    assert dup.status_code == 409 and "Replace it" in dup.json()["detail"]
    assert upload(client, student_h, "extra", imaging.face(seed=12)).status_code == 201
    assert upload(client, student_h, "extra", imaging.face(seed=13)).status_code == 201
    sixth = upload(client, student_h, "extra", imaging.face(seed=14))
    assert sixth.status_code == 409 and "at most 5" in sixth.json()["detail"]
    assert client.get(f"{API}/me/face-enrollment", headers=student_h).json()["photo_count"] == 5


def test_replace_and_delete(client, student_h, isolated_uploads, audit):
    photos = upload_all_required(client, student_h)
    before = set(files_on_disk(isolated_uploads))
    res = upload(client, student_h, None, imaging.face(seed=21), photo_id=photos["front"]["id"])
    assert res.status_code == 200 and res.json()["id"] == photos["front"]["id"]
    after = set(files_on_disk(isolated_uploads))
    assert len(after) == 3 and after != before  # old front file removed, new one in place

    res = client.delete(f"{API}/me/face-photos/{photos['left']['id']}", headers=student_h)
    assert res.status_code == 200 and res.json()["missing_poses"] == ["left"]
    assert len(files_on_disk(isolated_uploads)) == 2
    assert audit("face_photo.uploaded") and audit("face_photo.replaced") and audit("face_photo.deleted")
    # A failed replacement keeps the existing photo untouched.
    bad = upload(client, student_h, None, imaging.no_face(), photo_id=photos["front"]["id"])
    assert bad.status_code == 422 and len(files_on_disk(isolated_uploads)) == 2


# ── Status transitions and review ─────────────────────────────────────────


def test_submit_requires_front_left_right(client, student_h):
    upload(client, student_h, "front")
    res = client.post(f"{API}/me/face-enrollment/submit", headers=student_h)
    assert res.status_code == 422 and "left, right" in res.json()["detail"]


def test_full_review_cycle(client, student_h, hod_h, ids, audit):
    photos = upload_all_required(client, student_h)
    put_profile(client, student_h)
    res = client.post(f"{API}/me/face-enrollment/submit", headers=student_h)
    assert res.status_code == 200 and res.json()["status"] == "pending_review"
    assert client.post(f"{API}/me/face-enrollment/submit", headers=student_h).status_code == 409

    queue = client.get(f"{API}/face-enrollments", params={"status": "pending_review"}, headers=hod_h).json()
    assert [r["registration_no"] for r in queue["items"]] == ["F23CSE01"]
    assert queue["items"][0]["requirements_met"] is True and queue["items"][0]["has_profile_photo"] is True

    detail = client.get(f"{API}/face-enrollments/{ids['student']}", headers=hod_h).json()
    assert detail["registration_no"] == "F23CSE01" and detail["section_name"] == "A"
    assert detail["semester_name"] == "Semester 6" and len(detail["photos"]) == 3
    assert detail["profile_photo_url"] is not None

    res = client.post(f"{API}/face-enrollments/{ids['student']}/approve", headers=hod_h)
    assert res.status_code == 200 and res.json()["status"] == "approved"
    assert all(p["reviewed_at"] for p in res.json()["photos"])
    assert audit("face_enrollment.submitted") and audit("face_enrollment.approved")

    # Approved enrollments are locked for the student.
    for attempt in (upload(client, student_h, "extra"),
                    upload(client, student_h, None, photo_id=photos["front"]["id"]),
                    client.delete(f"{API}/me/face-photos/{photos['left']['id']}", headers=student_h)):
        assert attempt.status_code == 409 and "locked" in attempt.json()["detail"]

    # A reviewer can request a retake; the student sees the reason and can resubmit.
    assert client.post(f"{API}/face-enrollments/{ids['student']}/reject", json={"reason": " "},
                       headers=hod_h).status_code == 422
    res = client.post(f"{API}/face-enrollments/{ids['student']}/reject",
                      json={"reason": "Glasses glare — please retake front"}, headers=hod_h)
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    mine = client.get(f"{API}/me/face-enrollment", headers=student_h).json()
    assert mine["status"] == "rejected" and mine["review_note"] == "Glasses glare — please retake front"
    assert mine["reviewed_by_name"] == "Dr. Ayesha Khan" and mine["can_submit"] is True

    assert upload(client, student_h, None, imaging.face(seed=31), photo_id=photos["front"]["id"]).status_code == 200
    assert client.get(f"{API}/me/face-enrollment", headers=student_h).json()["status"] == "rejected"
    assert client.post(f"{API}/me/face-enrollment/submit", headers=student_h).json()["status"] == "pending_review"
    entry = audit("face_enrollment.rejected")[0]
    assert entry.new_value["reason"] == "Glasses glare — please retake front"


def test_changes_after_submission_withdraw_it(client, student_h, audit):
    photos = upload_all_required(client, student_h)
    client.post(f"{API}/me/face-enrollment/submit", headers=student_h)
    client.delete(f"{API}/me/face-photos/{photos['right']['id']}", headers=student_h)
    assert client.get(f"{API}/me/face-enrollment", headers=student_h).json()["status"] == "incomplete"
    assert audit("face_enrollment.withdrawn")


def test_approve_only_pending_and_reject_only_submitted(client, student_h, hod_h, ids):
    assert client.post(f"{API}/face-enrollments/{ids['student']}/approve", headers=hod_h).status_code == 409
    assert client.post(f"{API}/face-enrollments/{ids['student']}/reject", json={"reason": "No photos"},
                       headers=hod_h).status_code == 409


def test_account_and_face_approval_are_independent(client, hod_h, ids):
    pending = client.get(f"{API}/accounts/pending-students", headers=hod_h).json()["items"][0]
    assert pending["face_enrollment_status"] == "not_started"
    res = client.patch(f"{API}/accounts/{ids['pending_user']}/status", json={"status": "active"}, headers=hod_h)
    assert res.status_code == 200
    student = client.get(f"{API}/students/{ids['pending']}", headers=hod_h).json()
    assert student["status"] == "active" and student["face_enrollment_status"] == "not_started"


# ── Ownership, department isolation, image authorisation ──────────────────


def test_student_cannot_touch_another_students_photos(client, student_h, other_student_h):
    theirs = upload(client, other_student_h, "front").json()
    assert upload(client, student_h, None, photo_id=theirs["id"]).status_code == 404
    assert client.delete(f"{API}/me/face-photos/{theirs['id']}", headers=student_h).status_code == 404
    assert client.get(f"{API}{theirs['image_url']}", headers=student_h).status_code == 404
    assert client.get(f"{API}{theirs['image_url']}", headers=other_student_h).status_code == 200


def test_staff_cannot_use_student_upload_endpoints(client, hod_h, login):
    for headers in (hod_h, login(TEACHER_EMAIL)):
        assert upload(client, headers, "front").status_code == 403
        assert client.get(f"{API}/me/face-enrollment", headers=headers).status_code == 403


def test_students_and_teachers_cannot_review(client, student_h, login, ids):
    for headers in (student_h, login(TEACHER_EMAIL)):
        assert client.get(f"{API}/face-enrollments", headers=headers).status_code == 403
        assert client.post(f"{API}/face-enrollments/{ids['student']}/approve", headers=headers).status_code == 403


def test_hod_cross_department_denied(client, hod_h, admin_h, ee_hod_h, ee, login):
    ee_h = login("student.ee@test.edu")
    photos = upload_all_required(client, ee_h)
    client.post(f"{API}/me/face-enrollment/submit", headers=ee_h)
    assert client.get(f"{API}/face-enrollments/{ee['student']}", headers=hod_h).status_code == 404
    assert client.post(f"{API}/face-enrollments/{ee['student']}/approve", headers=hod_h).status_code == 404
    assert client.post(f"{API}/face-enrollments/{ee['student']}/reject", json={"reason": "nope"},
                       headers=hod_h).status_code == 404
    assert client.get(f"{API}{photos['front']['image_url']}", headers=hod_h).status_code == 404
    listed = client.get(f"{API}/face-enrollments", params={"q": "F24EE01"}, headers=hod_h).json()
    assert listed["total"] == 0
    # Face review belongs to the student's own HOD — not the super admin.
    assert client.get(f"{API}{photos['front']['image_url']}", headers=admin_h).status_code == 404
    assert client.get(f"{API}/face-enrollments", headers=admin_h).status_code == 403
    assert client.post(f"{API}/face-enrollments/{ee['student']}/approve", headers=admin_h).status_code == 403
    assert client.get(f"{API}{photos['front']['image_url']}", headers=ee_hod_h).status_code == 200
    assert client.post(f"{API}/face-enrollments/{ee['student']}/approve", headers=ee_hod_h).status_code == 200


def test_image_retrieval_authorisation(client, student_h, hod_h, admin_h, ids, ee, login):
    front = upload(client, student_h, "front").json()
    put_profile(client, student_h)
    face_url, profile_url = f"{API}{front['image_url']}", f"{API}/students/{ids['student']}/profile-photo"
    assert client.get(face_url).status_code == 401
    assert client.get(face_url, headers={"Authorization": "Bearer junk"}).status_code == 401
    for headers in (student_h, hod_h):
        assert client.get(face_url, headers=headers).status_code == 200
    for url in (face_url, profile_url):  # the super admin does not handle student data
        assert client.get(url, headers=admin_h).status_code == 404
    teacher_h = login(TEACHER_EMAIL)
    assert client.get(face_url, headers=teacher_h).status_code == 404  # biometric photos: never teachers
    assert client.get(profile_url, headers=teacher_h).status_code == 200  # teaches this student
    ee_teacher = login("teacher.ee@test.edu")
    assert client.get(profile_url, headers=ee_teacher).status_code == 404
    assert client.get(f"{API}/face-photos/999999/image", headers=admin_h).status_code == 404


def test_tampered_database_path_cannot_escape_uploads(client, student_h, db_session):
    photo = upload(client, student_h, "front").json()
    with db_session() as db:
        row = db.get(StudentFaceImage, photo["id"])
        row.image_path = "../../pyproject.toml"
        db.commit()
    assert client.get(f"{API}{photo['image_url']}", headers=student_h).status_code == 404


# ── Onboarding (pending students) ─────────────────────────────────────────


def _register(client, ids):
    return client.post(f"{API}/auth/register/student", json={
        "full_name": "New Student", "registration_no": "F23CSE77", "email": "new@test.edu",
        "password": "Student@123", "department_id": ids["cse"], "batch_id": ids["batch"],
        "semester_id": ids["semester"], "section_id": ids["section_a"]})


def test_registration_onboarding_flow(client, ids, hod_h):
    res = _register(client, ids)
    assert res.status_code == 201
    token = {"Authorization": f"Bearer {res.json()['onboarding_token']}"}
    assert res.json()["expires_in"] == settings.ONBOARDING_TOKEN_EXPIRE_MINUTES * 60

    assert put_profile(client, token).status_code == 200
    upload_all_required(client, token)
    assert client.post(f"{API}/me/face-enrollment/submit", headers=token).json()["status"] == "pending_review"
    # The onboarding token is useless anywhere else.
    assert client.get(f"{API}/auth/me", headers=token).status_code == 401
    assert client.get(f"{API}/face-enrollments", headers=token).status_code == 401
    assert client.get(f"{API}/dashboard/student/subjects", headers=token).status_code == 401
    # Pending students still cannot sign in normally.
    assert client.post(f"{API}/auth/login", json={"email": "new@test.edu", "password": "Student@123"}).status_code == 403
    # The HOD sees the account approval *and* the face status.
    pending = client.get(f"{API}/accounts/pending-students", headers=hod_h).json()["items"]
    assert {p["registration_no"]: p["face_enrollment_status"] for p in pending}["F23CSE77"] == "pending_review"


def test_onboarding_token_endpoint(client, ids, student_h):
    _register(client, ids)
    ok = client.post(f"{API}/auth/onboarding-token", json={"email": "new@test.edu", "password": "Student@123"})
    assert ok.status_code == 200 and ok.json()["onboarding_token"]
    assert client.post(f"{API}/auth/onboarding-token",
                       json={"email": "new@test.edu", "password": "Wrong@1234"}).status_code == 401
    approved = client.post(f"{API}/auth/onboarding-token", json={"email": STUDENT_EMAIL, "password": "Demo@1234"})
    assert approved.status_code == 409  # approved students use normal sign-in
    staff = client.post(f"{API}/auth/onboarding-token", json={"email": TEACHER_EMAIL, "password": "Demo@1234"})
    assert staff.status_code == 403


def test_rejected_registration_loses_onboarding_access(client, ids, hod_h, db_session):
    token = {"Authorization": f"Bearer {_register(client, ids).json()['onboarding_token']}"}
    with db_session() as db:
        user_id = db.scalar(select(Student.user_id).where(Student.registration_no == "F23CSE77"))
    client.patch(f"{API}/accounts/{user_id}/status", json={"status": "rejected", "reason": "Not enrolled"},
                 headers=hod_h)
    assert client.get(f"{API}/me/face-enrollment", headers=token).status_code == 401  # token revoked


# ── Size limit, audit privacy ─────────────────────────────────────────────


def test_oversized_upload_rejected_before_parsing(client, student_h, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.01)
    res = upload(client, student_h, "front")
    assert res.status_code == 413 and "too large" in res.json()["detail"]


def test_audit_holds_metadata_only(client, student_h, hod_h, ids, db_session):
    upload_all_required(client, student_h)
    put_profile(client, student_h)
    client.post(f"{API}/me/face-enrollment/submit", headers=student_h)
    client.post(f"{API}/face-enrollments/{ids['student']}/approve", headers=hod_h)
    with db_session() as db:
        entries = db.scalars(select(AuditLog).where(
            AuditLog.action.like("face%") | AuditLog.action.like("profile_photo%"))).all()
    assert {e.action for e in entries} >= {"face_photo.uploaded", "profile_photo.uploaded",
                                          "face_enrollment.submitted", "face_enrollment.approved"}
    dump = json.dumps([[e.old_value, e.new_value] for e in entries])
    assert "faces/" not in dump and "profiles/" not in dump and ".jpg" not in dump  # no paths
    assert len(dump) < 5000  # metadata only — no image bytes or base64
    assert all(e.ip_address for e in entries)


def test_timestamps_are_serialised_as_utc(client, student_h, hod_h):
    """SQLite returns naive datetimes; the API must still label them UTC so browsers
    don't shift them into local time."""
    upload(client, student_h, "front")
    photo = client.get(f"{API}/me/face-enrollment", headers=student_h).json()["photos"][0]
    assert photo["uploaded_at"].endswith(("Z", "+00:00"))
    student = client.get(f"{API}/students", params={"q": "F23CSE01"}, headers=hod_h).json()["items"][0]
    assert student["created_at"].endswith(("Z", "+00:00"))
