"""Profile photos, face-enrollment photos and their review.

Lifecycle (students.face_enrollment_status) — independent of account approval:

    not_started ──upload──▶ incomplete ──submit (front+left+right)──▶ pending_review
         ▲                     ▲   │                                     │      │
         └──delete all─────────┘   └──── any change withdraws ◀──────────┘      │
                                                                           approve│reject
    rejected ◀──────────────── reject (reason) ◀── approved ◀───────────────────┘
       └── student fixes photos, then submits again ──▶ pending_review

An approved enrollment is locked: photos cannot change until a reviewer requests a retake.
Audit entries carry metadata only — never image bytes or file paths.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.auth.dependencies import scoped_department_id
from backend.app.core.config import settings
from backend.app.models import (
    AccountStatus,
    Batch,
    Department,
    FaceEnrollmentStatus,
    FaceImageType,
    Section,
    Semester,
    Student,
    StudentCourseEnrollment,
    StudentFaceImage,
    TeacherCourseAssignment,
    User,
    UserRole,
)
from backend.app.schemas.common import Page
from backend.app.schemas.face import (
    REQUIRED_POSES,
    FaceEnrollmentDetail,
    FaceEnrollmentListItem,
    FaceEnrollmentOut,
    FacePhotoOut,
)
from backend.app.services import storage
from backend.app.services.audit_service import record_audit
from backend.app.services.face_embedding_service import invalidate_student
from backend.app.services.image_validation import ImageRejected, validate_face_photo, validate_profile_photo
from backend.app.services.scoping import apply_scope, get_in_scope, like, not_found, paginate

_POSE_ORDER = {FaceImageType.FRONT: 0, FaceImageType.LEFT: 1, FaceImageType.RIGHT: 2, FaceImageType.EXTRA: 3}
_POSE_LABEL = {FaceImageType.FRONT: "front", FaceImageType.LEFT: "left", FaceImageType.RIGHT: "right",
               FaceImageType.EXTRA: "extra"}


def _now() -> datetime:
    return datetime.now(UTC)


def _version(ts: datetime | None) -> str:
    return str(int(ts.timestamp())) if ts else "0"


def max_extra_photos() -> int:
    return settings.FACE_MAX_PHOTOS - len(REQUIRED_POSES)


# ── Read models ────────────────────────────────────────────────────────────


def _photos(db: Session, student_id: int) -> list[StudentFaceImage]:
    rows = db.scalars(select(StudentFaceImage).where(StudentFaceImage.student_id == student_id)).all()
    return sorted(rows, key=lambda p: (_POSE_ORDER[p.image_type], p.created_at, p.id))


def _photo_out(photo: StudentFaceImage) -> FacePhotoOut:
    return FacePhotoOut(
        id=photo.id, pose=photo.image_type, validation_status=photo.validation_status,
        validation_message=photo.validation_message, checks=(photo.quality or {}).get("checks", []),
        width=photo.width, height=photo.height, file_size=photo.file_size, uploaded_at=photo.created_at,
        updated_at=photo.updated_at, reviewed_at=photo.reviewed_at,
        image_url=f"/face-photos/{photo.id}/image?v={_version(photo.updated_at)}",
    )


def _missing(photos: list[StudentFaceImage]) -> list[FaceImageType]:
    have = {p.image_type for p in photos if p.is_usable}
    return [pose for pose in REQUIRED_POSES if pose not in have]


def enrollment_view(db: Session, student: Student) -> FaceEnrollmentOut:
    photos = _photos(db, student.id)
    missing = _missing(photos)
    status_ = student.face_enrollment_status
    reviewer = db.get(User, student.face_reviewed_by_id) if student.face_reviewed_by_id else None
    return FaceEnrollmentOut(
        student_id=student.id, status=status_, requirements_met=not missing, missing_poses=missing,
        photo_count=len(photos), max_photos=settings.FACE_MAX_PHOTOS, max_extra_photos=max_extra_photos(),
        can_edit=status_ != FaceEnrollmentStatus.APPROVED,
        can_submit=not missing and status_ in (FaceEnrollmentStatus.INCOMPLETE, FaceEnrollmentStatus.REJECTED),
        photos=[_photo_out(p) for p in photos],
        profile_photo_url=(f"/students/{student.id}/profile-photo?v={_version(student.profile_photo_updated_at)}"
                           if student.profile_photo_path else None),
        profile_photo_updated_at=student.profile_photo_updated_at,
        submitted_at=student.face_submitted_at, reviewed_at=student.face_reviewed_at,
        reviewed_by_name=reviewer.full_name if reviewer else None, review_note=student.face_review_note,
    )


# ── Student actions ────────────────────────────────────────────────────────


def _student_of(user: User) -> Student:
    return user.student_profile


def _reject_http(exc: ImageRejected) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


def _ensure_editable(student: Student) -> None:
    if student.face_enrollment_status == FaceEnrollmentStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Your face enrollment is approved and locked. Ask your department to request a "
                            "retake if your photos need to change.")


def _after_change(db: Session, student: Student, actor: User, request: Request) -> None:
    """Keep the enrollment status consistent after photos were added, replaced or removed."""
    if student.face_enrollment_status == FaceEnrollmentStatus.PENDING_REVIEW:
        student.face_enrollment_status = FaceEnrollmentStatus.INCOMPLETE
        student.face_submitted_at = None
        record_audit(db, actor=actor, action="face_enrollment.withdrawn", entity="student", entity_id=student.id,
                     department_id=student.department_id,
                     old_value={"status": FaceEnrollmentStatus.PENDING_REVIEW.value},
                     new_value={"status": FaceEnrollmentStatus.INCOMPLETE.value, "reason": "photos changed"},
                     request=request)
    elif student.face_enrollment_status in (FaceEnrollmentStatus.NOT_STARTED, FaceEnrollmentStatus.INCOMPLETE):
        count = db.scalar(select(func.count(StudentFaceImage.id)).where(StudentFaceImage.student_id == student.id))
        student.face_enrollment_status = FaceEnrollmentStatus.INCOMPLETE if count else FaceEnrollmentStatus.NOT_STARTED
    # REJECTED stays visible (with its reason) until the student submits again.


def _commit_or_cleanup(db: Session, new_path: str, *, flush_only: bool = False) -> None:
    """Flush/commit; if the database write fails, remove the file we just stored."""
    try:
        db.flush() if flush_only else db.commit()
    except Exception:
        db.rollback()
        storage.delete(new_path)
        raise


def _photo_meta(photo: StudentFaceImage) -> dict:
    return {"photo_id": photo.id, "pose": photo.image_type.value, "validation_status": photo.validation_status.value,
            "width": photo.width, "height": photo.height, "file_size": photo.file_size}


def upload_profile_photo(db: Session, user: User, data: bytes, content_type: str | None,
                         request: Request) -> FaceEnrollmentOut:
    student = _student_of(user)
    try:
        processed = validate_profile_photo(data, content_type)
    except ImageRejected as exc:
        raise _reject_http(exc) from None
    old_path = student.profile_photo_path
    new_path = storage.save("profiles", student.id, processed.jpeg)
    student.profile_photo_path = new_path
    student.profile_photo_updated_at = _now()
    record_audit(db, actor=user, action="profile_photo.replaced" if old_path else "profile_photo.uploaded",
                 entity="student", entity_id=student.id, department_id=student.department_id,
                 new_value={"width": processed.width, "height": processed.height, "file_size": len(processed.jpeg)},
                 request=request)
    _commit_or_cleanup(db, new_path)
    storage.delete(old_path)  # only after the new photo is safely recorded
    return enrollment_view(db, student)


def add_face_photo(db: Session, user: User, pose: FaceImageType, data: bytes, content_type: str | None,
                   request: Request) -> FacePhotoOut:
    student = _student_of(user)
    _ensure_editable(student)
    photos = _photos(db, student.id)
    if len(photos) >= settings.FACE_MAX_PHOTOS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"You can upload at most {settings.FACE_MAX_PHOTOS} face photos. Replace or delete one first.")
    same_pose = [p for p in photos if p.image_type == pose]
    if pose in REQUIRED_POSES and same_pose:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"You already have a {_POSE_LABEL[pose]} photo. Replace it instead of adding another.")
    if pose == FaceImageType.EXTRA and len(same_pose) >= max_extra_photos():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"You can add at most {max_extra_photos()} extra photos.")
    try:
        processed = validate_face_photo(data, content_type)
    except ImageRejected as exc:
        raise _reject_http(exc) from None

    new_path = storage.save("faces", student.id, processed.jpeg)
    photo = StudentFaceImage(
        student_id=student.id, image_path=new_path, image_type=pose, is_usable=True,
        validation_status=processed.status, validation_message=processed.message, quality=processed.quality,
        width=processed.width, height=processed.height, file_size=len(processed.jpeg),
    )
    db.add(photo)
    _commit_or_cleanup(db, new_path, flush_only=True)
    _after_change(db, student, user, request)
    record_audit(db, actor=user, action="face_photo.uploaded", entity="student_face_image", entity_id=photo.id,
                 department_id=student.department_id, new_value=_photo_meta(photo), request=request)
    _commit_or_cleanup(db, new_path)
    db.refresh(photo)
    return _photo_out(photo)


def _own_photo(db: Session, user: User, photo_id: int) -> StudentFaceImage:
    photo = db.get(StudentFaceImage, photo_id)
    if photo is None or photo.student_id != _student_of(user).id:
        raise not_found("Photo")  # another student's photo looks exactly like a missing one
    return photo


def replace_face_photo(db: Session, user: User, photo_id: int, data: bytes, content_type: str | None,
                       request: Request) -> FacePhotoOut:
    student = _student_of(user)
    photo = _own_photo(db, user, photo_id)
    _ensure_editable(student)
    try:
        processed = validate_face_photo(data, content_type)
    except ImageRejected as exc:
        raise _reject_http(exc) from None
    old_meta, old_path = _photo_meta(photo), photo.image_path
    new_path = storage.save("faces", student.id, processed.jpeg)
    photo.image_path = new_path
    photo.validation_status, photo.validation_message = processed.status, processed.message
    photo.quality, photo.width, photo.height = processed.quality, processed.width, processed.height
    photo.file_size, photo.is_usable = len(processed.jpeg), True
    photo.updated_at = _now()
    photo.reviewed_at, photo.reviewed_by_id = None, None
    _after_change(db, student, user, request)
    record_audit(db, actor=user, action="face_photo.replaced", entity="student_face_image", entity_id=photo.id,
                 department_id=student.department_id, old_value=old_meta, new_value=_photo_meta(photo),
                 request=request)
    _commit_or_cleanup(db, new_path)
    storage.delete(old_path)
    db.refresh(photo)
    return _photo_out(photo)


def delete_face_photo(db: Session, user: User, photo_id: int, request: Request) -> FaceEnrollmentOut:
    student = _student_of(user)
    photo = _own_photo(db, user, photo_id)
    _ensure_editable(student)  # approved photos cannot be deleted (integrity of the approved set)
    meta, path = _photo_meta(photo), photo.image_path
    db.delete(photo)
    db.flush()
    _after_change(db, student, user, request)
    record_audit(db, actor=user, action="face_photo.deleted", entity="student_face_image", entity_id=meta["photo_id"],
                 department_id=student.department_id, old_value=meta, request=request)
    db.commit()
    storage.delete(path)
    return enrollment_view(db, student)


def submit_for_review(db: Session, user: User, request: Request) -> FaceEnrollmentOut:
    student = _student_of(user)
    if student.face_enrollment_status == FaceEnrollmentStatus.PENDING_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your photos are already waiting for review.")
    _ensure_editable(student)
    missing = _missing(_photos(db, student.id))
    if missing:
        names = ", ".join(_POSE_LABEL[p] for p in missing)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Add a valid {names} photo before submitting.")
    old = student.face_enrollment_status
    student.face_enrollment_status = FaceEnrollmentStatus.PENDING_REVIEW
    student.face_submitted_at = _now()
    record_audit(db, actor=user, action="face_enrollment.submitted", entity="student", entity_id=student.id,
                 department_id=student.department_id, old_value={"status": old.value},
                 new_value={"status": FaceEnrollmentStatus.PENDING_REVIEW.value}, request=request)
    db.commit()
    return enrollment_view(db, student)


# ── Review (super admin / HOD) ─────────────────────────────────────────────


def list_enrollments(db: Session, actor: User, *, page: int, page_size: int, q: str | None = None,
                     status_filter: FaceEnrollmentStatus | None = None, department_id: int | None = None,
                     batch_id: int | None = None, semester_id: int | None = None,
                     section_id: int | None = None) -> Page[FaceEnrollmentListItem]:
    photo_count = select(func.count(StudentFaceImage.id)).where(
        StudentFaceImage.student_id == Student.id).scalar_subquery()
    required = select(func.count(func.distinct(StudentFaceImage.image_type))).where(
        StudentFaceImage.student_id == Student.id, StudentFaceImage.is_usable.is_(True),
        StudentFaceImage.image_type.in_(REQUIRED_POSES)).scalar_subquery()
    stmt = (
        select(Student, User, Department.code, Batch.name, Semester.name, Section.name, photo_count, required)
        .join(User, User.id == Student.user_id)
        .join(Department, Department.id == Student.department_id)
        .join(Batch, Batch.id == Student.batch_id)
        .join(Semester, Semester.id == Student.semester_id)
        .join(Section, Section.id == Student.section_id)
    )
    stmt = apply_scope(stmt, Student.department_id, actor, department_id)
    if status_filter is not None:
        stmt = stmt.where(Student.face_enrollment_status == status_filter)
    for column, value in ((Student.batch_id, batch_id), (Student.semester_id, semester_id),
                          (Student.section_id, section_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    if q:
        pattern = like(q)
        stmt = stmt.where(or_(func.lower(User.full_name).like(pattern, escape="\\"),
                              func.lower(Student.registration_no).like(pattern, escape="\\"),
                              func.lower(User.email).like(pattern, escape="\\")))
    # Oldest submissions first, so the review queue is worked in order.
    stmt = stmt.order_by(Student.face_submitted_at.is_(None), Student.face_submitted_at, Student.registration_no)

    def row(r) -> FaceEnrollmentListItem:
        student, user, code, batch, semester, section, count, req = r
        return FaceEnrollmentListItem(
            student_id=student.id, user_id=user.id, full_name=user.full_name, registration_no=student.registration_no,
            account_status=user.status, department_id=student.department_id, department_code=code,
            batch_name=batch, semester_name=semester, section_name=section, status=student.face_enrollment_status,
            photo_count=count, requirements_met=req == len(REQUIRED_POSES),
            has_profile_photo=student.profile_photo_path is not None, submitted_at=student.face_submitted_at,
            reviewed_at=student.face_reviewed_at,
        )

    return paginate(db, stmt, page, page_size, row)


def enrollment_detail(db: Session, actor: User, student_id: int) -> FaceEnrollmentDetail:
    student = get_in_scope(db, Student, student_id, actor, "Student")
    base = enrollment_view(db, student)
    dept = db.get(Department, student.department_id)
    return FaceEnrollmentDetail(
        **base.model_dump(), user_id=student.user_id, full_name=student.user.full_name, email=student.user.email,
        registration_no=student.registration_no, account_status=student.user.status, department_id=dept.id,
        department_name=dept.name, department_code=dept.code, batch_name=db.get(Batch, student.batch_id).name,
        semester_name=db.get(Semester, student.semester_id).name, section_name=db.get(Section, student.section_id).name,
    )


def approve(db: Session, actor: User, student_id: int, request: Request) -> FaceEnrollmentDetail:
    student = get_in_scope(db, Student, student_id, actor, "Student")
    if student.face_enrollment_status != FaceEnrollmentStatus.PENDING_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only enrollments waiting for review can be approved")
    photos = _photos(db, student.id)
    if _missing(photos):
        raise HTTPException(status.HTTP_409_CONFLICT, "Front, left and right photos are required for approval")
    now = _now()
    student.face_enrollment_status = FaceEnrollmentStatus.APPROVED
    student.face_reviewed_at, student.face_reviewed_by_id, student.face_review_note = now, actor.id, None
    for photo in photos:
        photo.reviewed_at, photo.reviewed_by_id = now, actor.id
    record_audit(db, actor=actor, action="face_enrollment.approved", entity="student", entity_id=student.id,
                 department_id=student.department_id,
                 old_value={"status": FaceEnrollmentStatus.PENDING_REVIEW.value},
                 new_value={"status": FaceEnrollmentStatus.APPROVED.value, "photo_ids": [p.id for p in photos]},
                 request=request)
    db.commit()
    return enrollment_detail(db, actor, student.id)


def reject(db: Session, actor: User, student_id: int, reason: str, request: Request) -> FaceEnrollmentDetail:
    student = get_in_scope(db, Student, student_id, actor, "Student")
    old = student.face_enrollment_status
    if old not in (FaceEnrollmentStatus.PENDING_REVIEW, FaceEnrollmentStatus.APPROVED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only submitted or approved enrollments can be sent back for a retake")
    student.face_enrollment_status = FaceEnrollmentStatus.REJECTED
    student.face_reviewed_at, student.face_reviewed_by_id, student.face_review_note = _now(), actor.id, reason
    student.face_submitted_at = None
    removed = invalidate_student(db, student.id)  # stale biometric templates must never be used
    record_audit(db, actor=actor, action="face_enrollment.rejected", entity="student", entity_id=student.id,
                 department_id=student.department_id, old_value={"status": old.value},
                 new_value={"status": FaceEnrollmentStatus.REJECTED.value, "reason": reason,
                            "embeddings_removed": removed}, request=request)
    db.commit()
    return enrollment_detail(db, actor, student.id)


# ── Image retrieval (authorised) ───────────────────────────────────────────


def _can_view(db: Session, viewer: User, student: Student, *, face: bool) -> bool:
    # The super admin administers staff, not students: no access to student photos.
    if viewer.role == UserRole.STUDENT:
        return viewer.student_profile is not None and viewer.student_profile.id == student.id
    if viewer.role == UserRole.HOD:
        return scoped_department_id(viewer) == student.department_id
    if viewer.role == UserRole.TEACHER and not face and viewer.teacher_profile is not None:
        # Teachers may see profile photos of students in classes they actively teach.
        return db.scalar(
            select(StudentCourseEnrollment.id)
            .join(TeacherCourseAssignment, (TeacherCourseAssignment.course_id == StudentCourseEnrollment.course_id)
                  & (TeacherCourseAssignment.section_id == StudentCourseEnrollment.section_id))
            .where(StudentCourseEnrollment.student_id == student.id, StudentCourseEnrollment.is_active.is_(True),
                   TeacherCourseAssignment.teacher_id == viewer.teacher_profile.id,
                   TeacherCourseAssignment.is_active.is_(True))
            .limit(1)
        ) is not None
    return False


def _read(path: str) -> bytes:
    try:
        return storage.read(path)
    except storage.StorageError:
        raise not_found("Image") from None


def face_photo_bytes(db: Session, viewer: User, photo_id: int) -> bytes:
    photo = db.get(StudentFaceImage, photo_id)
    student = db.get(Student, photo.student_id) if photo else None
    if photo is None or student is None or not _can_view(db, viewer, student, face=True):
        raise not_found("Image")
    return _read(photo.image_path)


def profile_photo_bytes(db: Session, viewer: User, student_id: int) -> bytes:
    student = db.get(Student, student_id)
    if student is None or not student.profile_photo_path or not _can_view(db, viewer, student, face=False):
        raise not_found("Image")
    return _read(student.profile_photo_path)


def recognition_eligible(student: Student) -> bool:
    """Phase 6 hook: only active accounts with an approved face enrollment are matched."""
    return student.user.status == AccountStatus.ACTIVE and \
        student.face_enrollment_status == FaceEnrollmentStatus.APPROVED
