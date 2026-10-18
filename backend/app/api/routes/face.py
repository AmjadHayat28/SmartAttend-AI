"""Profile photo, face-enrollment photos, review and authorised image retrieval (Phase 4)."""

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, Response, UploadFile, status

from backend.app.api.params import Paging
from backend.app.auth.dependencies import HodUser, DbSession, EnrollingStudent, ImageViewer
from backend.app.models import FaceEnrollmentStatus, FaceImageType
from backend.app.schemas.common import Page
from backend.app.schemas.face import (
    FaceEnrollmentDetail,
    FaceEnrollmentListItem,
    FaceEnrollmentOut,
    FacePhotoOut,
    FaceReviewReject,
)
from backend.app.services import face_enrollment_service as svc
from backend.app.services.face_embedding_service import generate_in_background
from backend.app.services.image_validation import max_upload_bytes

router = APIRouter(tags=["face enrollment"])

_IMAGE_HEADERS = {
    "Cache-Control": "private, no-store",  # sensitive biometric source images: never cache in shared caches
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": 'inline; filename="photo.jpg"',
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


def _read_upload(file: UploadFile) -> tuple[bytes, str | None]:
    """Read at most the configured limit (+1 byte, to detect oversize) without trusting headers."""
    data = file.file.read(max_upload_bytes() + 1)
    return data, file.content_type


# ── Student: own enrollment (access token, or onboarding token while pending) ──


@router.get("/me/face-enrollment", response_model=FaceEnrollmentOut)
def my_enrollment(user: EnrollingStudent, db: DbSession):
    return svc.enrollment_view(db, user.student_profile)


@router.put("/me/profile-photo", response_model=FaceEnrollmentOut)
def upload_profile_photo(request: Request, user: EnrollingStudent, db: DbSession, file: UploadFile = File(...)):
    data, content_type = _read_upload(file)
    return svc.upload_profile_photo(db, user, data, content_type, request)


@router.post("/me/face-photos", response_model=FacePhotoOut, status_code=status.HTTP_201_CREATED)
def upload_face_photo(request: Request, user: EnrollingStudent, db: DbSession,
                      pose: FaceImageType = Form(...), file: UploadFile = File(...)):
    data, content_type = _read_upload(file)
    return svc.add_face_photo(db, user, pose, data, content_type, request)


@router.put("/me/face-photos/{photo_id}", response_model=FacePhotoOut)
def replace_face_photo(photo_id: int, request: Request, user: EnrollingStudent, db: DbSession,
                       file: UploadFile = File(...)):
    data, content_type = _read_upload(file)
    return svc.replace_face_photo(db, user, photo_id, data, content_type, request)


@router.delete("/me/face-photos/{photo_id}", response_model=FaceEnrollmentOut)
def delete_face_photo(photo_id: int, request: Request, user: EnrollingStudent, db: DbSession):
    return svc.delete_face_photo(db, user, photo_id, request)


@router.post("/me/face-enrollment/submit", response_model=FaceEnrollmentOut)
def submit_enrollment(request: Request, user: EnrollingStudent, db: DbSession):
    return svc.submit_for_review(db, user, request)


# ── Authorised image retrieval ──────────────────────────────────────────────


@router.get("/face-photos/{photo_id}/image", response_class=Response)
def face_photo_image(photo_id: int, viewer: ImageViewer, db: DbSession):
    """Owner student, super admin, or the student's HOD. Everyone else gets 404."""
    return Response(svc.face_photo_bytes(db, viewer, photo_id), media_type="image/jpeg", headers=_IMAGE_HEADERS)


@router.get("/students/{student_id}/profile-photo", response_class=Response)
def profile_photo_image(student_id: int, viewer: ImageViewer, db: DbSession):
    """Owner, super admin, the student's HOD, or a teacher who teaches the student."""
    return Response(svc.profile_photo_bytes(db, viewer, student_id), media_type="image/jpeg", headers=_IMAGE_HEADERS)


# ── Review (super admin: all; HOD: own department) ──────────────────────────


@router.get("/face-enrollments", response_model=Page[FaceEnrollmentListItem])
def list_enrollments(user: HodUser, db: DbSession, p: Paging,
                     status_filter: FaceEnrollmentStatus | None = Query(None, alias="status"),
                     department_id: int | None = None, batch_id: int | None = None,
                     semester_id: int | None = None, section_id: int | None = None):
    return svc.list_enrollments(db, user, page=p.page, page_size=p.page_size, q=p.q, status_filter=status_filter,
                                department_id=department_id, batch_id=batch_id, semester_id=semester_id,
                                section_id=section_id)


@router.get("/face-enrollments/{student_id}", response_model=FaceEnrollmentDetail)
def enrollment_detail(student_id: int, user: HodUser, db: DbSession):
    return svc.enrollment_detail(db, user, student_id)


@router.post("/face-enrollments/{student_id}/approve", response_model=FaceEnrollmentDetail)
def approve(student_id: int, request: Request, background: BackgroundTasks, user: HodUser, db: DbSession):
    """Approve; recognition embeddings are generated in the background right after the response
    (and, as a fallback, automatically before the next recognition run)."""
    result = svc.approve(db, user, student_id, request)
    background.add_task(generate_in_background, db.get_bind(), student_id)
    return result


@router.post("/face-enrollments/{student_id}/reject", response_model=FaceEnrollmentDetail)
def reject(student_id: int, data: FaceReviewReject, request: Request, user: HodUser, db: DbSession):
    """Reject a submission or request a retake of an approved enrollment. The reason is shown to the student."""
    return svc.reject(db, user, student_id, data.reason, request)

