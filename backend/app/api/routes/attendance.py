"""Attendance sessions (Phase 5). Teacher-only: a teacher takes, reviews, corrects and deletes
attendance for their own assigned classes. Every endpoint here refuses HODs and the super
admin (403); students see their own attendance through /dashboard/student/... instead."""

from datetime import date

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status

from backend.app.api.params import Paging
from backend.app.auth.dependencies import DbSession, TeacherUser
from backend.app.models import SessionStatus
from backend.app.schemas.attendance import (
    AttendanceClassOut,
    BulkUpdate,
    CancelRequest,
    CorrectionRequest,
    DeleteRequest,
    RecordsUpdate,
    SessionDetail,
    SessionListItem,
    SessionNoteUpdate,
    SessionStart,
    SessionStartOut,
    VersionedAction,
)
from backend.app.schemas.common import Page
from backend.app.schemas.recognition import (
    FaceAssignRequest,
    FaceDecisionRequest,
    RecognitionActionOut,
    RecognitionOut,
    RunRequest,
)
from backend.app.services import attendance_service as svc
from backend.app.services import recognition_service as rec
from backend.app.services.image_validation import max_upload_bytes

router = APIRouter(prefix="/attendance", tags=["attendance"])

_IMAGE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": 'inline; filename="classroom.jpg"',
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


# ── Teacher ────────────────────────────────────────────────────────────────


@router.get("/classes", response_model=list[AttendanceClassOut])
def my_classes(user: TeacherUser, db: DbSession):
    """The teacher's active assignments, with roster size, class % and any open draft."""
    return svc.list_classes(db, user)


@router.post("/sessions", response_model=SessionStartOut)
def start_session(data: SessionStart, request: Request, response: Response, user: TeacherUser, db: DbSession):
    """Create a draft for (assignment, date, session number), or resume the teacher's own draft.
    A finalized session for the same slot is refused with 409."""
    result = svc.start_session(db, user, data, request)
    response.status_code = status.HTTP_200_OK if result.resumed else status.HTTP_201_CREATED
    return result


@router.patch("/sessions/{session_id}/records", response_model=SessionDetail)
def update_records(session_id: int, data: RecordsUpdate, request: Request, user: TeacherUser, db: DbSession):
    return svc.update_records(db, user, session_id, data, request)


@router.post("/sessions/{session_id}/bulk", response_model=SessionDetail)
def bulk_update(session_id: int, data: BulkUpdate, request: Request, user: TeacherUser, db: DbSession):
    return svc.bulk_update(db, user, session_id, data, request)


@router.patch("/sessions/{session_id}", response_model=SessionDetail)
def update_note(session_id: int, data: SessionNoteUpdate, request: Request, user: TeacherUser, db: DbSession):
    return svc.update_note(db, user, session_id, data, request)


@router.post("/sessions/{session_id}/images", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
def upload_image(session_id: int, request: Request, user: TeacherUser, db: DbSession, file: UploadFile = File(...)):
    data = file.file.read(max_upload_bytes() + 1)
    return svc.add_image(db, user, session_id, data, file.content_type, request)


@router.delete("/sessions/{session_id}/images/{image_id}", response_model=SessionDetail)
def remove_image(session_id: int, image_id: int, request: Request, user: TeacherUser, db: DbSession):
    return svc.remove_image(db, user, session_id, image_id, request)


@router.post("/sessions/{session_id}/finalize", response_model=SessionDetail)
def finalize(session_id: int, data: VersionedAction, request: Request, user: TeacherUser, db: DbSession):
    return svc.finalize(db, user, session_id, data.version, request)


@router.post("/sessions/{session_id}/cancel", response_model=SessionDetail)
def cancel(session_id: int, data: CancelRequest, request: Request, user: TeacherUser, db: DbSession):
    return svc.cancel(db, user, session_id, data, request)


# ── History, corrections, deletion (the session's own teacher) ─────────────


@router.get("/sessions", response_model=Page[SessionListItem])
def list_sessions(user: TeacherUser, db: DbSession, p: Paging,
                  status_filter: SessionStatus | None = Query(None, alias="status"),
                  date_from: date | None = None, date_to: date | None = None,
                  course_id: int | None = None, semester_id: int | None = None, section_id: int | None = None):
    """The teacher's own attendance history."""
    return svc.list_sessions(db, user, page=p.page, page_size=p.page_size, q=p.q, status_filter=status_filter,
                             date_from=date_from, date_to=date_to, course_id=course_id,
                             semester_id=semester_id, section_id=section_id)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: int, user: TeacherUser, db: DbSession):
    return svc.get_session(db, user, session_id)


@router.post("/records/{record_id}/correct", response_model=SessionDetail)
def correct_record(record_id: int, data: CorrectionRequest, request: Request, user: TeacherUser, db: DbSession):
    """Correct a finalized record (reason required): the session's teacher only, within
    ATTENDANCE_TEACHER_CORRECTION_HOURS of finalizing. After that the attendance is locked."""
    return svc.correct_record(db, user, record_id, data, request)


@router.post("/sessions/{session_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, data: DeleteRequest, request: Request, user: TeacherUser, db: DbSession):
    """Delete Attendance: permanently delete this one finalized session (reason required) with its
    records, corrections, recognition results and classroom photos. Only a minimal audit event is
    kept. Only the session's teacher, within ATTENDANCE_TEACHER_CORRECTION_HOURS of finalizing. (POST, not DELETE, because a reason body is
    required — some proxies drop DELETE bodies.)"""
    svc.delete_session(db, user, session_id, data, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/images/{image_id}", response_class=Response)
def classroom_image(image_id: int, user: TeacherUser, db: DbSession):
    return Response(svc.image_bytes(db, user, image_id), media_type="image/jpeg", headers=_IMAGE_HEADERS)


# ── Face recognition (Phase 6) — pre-fills a draft; the teacher reviews and finalizes ──


@router.post("/sessions/{session_id}/recognition", response_model=RecognitionActionOut)
def run_recognition(session_id: int, data: RunRequest, request: Request, user: TeacherUser, db: DbSession):
    """Detect faces in the session's classroom photos and match them against the session roster
    only. Confident matches pre-fill Present on *unmarked* students; everything else waits for the
    teacher. Never finalizes and never marks anyone absent. Can be re-run while the session is a draft."""
    return rec.run_recognition(db, user, session_id, data.version, request)


@router.get("/sessions/{session_id}/recognition", response_model=RecognitionOut)
def get_recognition(session_id: int, user: TeacherUser, db: DbSession):
    """Latest run and its detected faces (boxes, suggestions, decisions — never embeddings)."""
    return rec.get_recognition(db, user, session_id)


@router.post("/recognition/faces/{face_id}/accept", response_model=RecognitionActionOut)
def accept_face(face_id: int, data: FaceDecisionRequest, request: Request, user: TeacherUser, db: DbSession):
    return rec.accept(db, user, face_id, data.version, request)


@router.post("/recognition/faces/{face_id}/assign", response_model=RecognitionActionOut)
def assign_face(face_id: int, data: FaceAssignRequest, request: Request, user: TeacherUser, db: DbSession):
    """Link a detected face to a student on this session's roster (only roster students allowed)."""
    return rec.assign(db, user, face_id, data.student_id, data.version, data.replace, request)


@router.post("/recognition/faces/{face_id}/reject", response_model=RecognitionActionOut)
def reject_face(face_id: int, data: FaceDecisionRequest, request: Request, user: TeacherUser, db: DbSession):
    return rec.reject(db, user, face_id, data.version, request)
