"""Face-recognition results for the attendance editor.

Deliberately contains no vectors: only boxes, suggested students, scores and decisions.
"""

from pydantic import BaseModel

from backend.app.models import FaceDecision, RecognitionCategory, RecognitionRunStatus
from backend.app.schemas.attendance import SessionDetail
from backend.app.schemas.types import UTCDateTime


class StudentRef(BaseModel):
    student_id: int
    registration_no: str
    full_name: str


class BoundingBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class RecognitionFaceOut(BaseModel):
    id: int
    image_id: int
    image_width: int
    image_height: int
    face_index: int
    bbox: BoundingBox
    det_score: float
    category: RecognitionCategory
    suggested: StudentRef | None
    similarity: float | None
    second: StudentRef | None
    second_similarity: float | None
    is_primary: bool  # False = this student's strongest sighting is in another photo
    decision: FaceDecision
    assigned: StudentRef | None


class RecognitionRunOut(BaseModel):
    id: int
    status: RecognitionRunStatus
    # While processing: the step the server is really on (detecting | matching | saving) and the
    # number of photos already analysed. None once the run has finished.
    stage: str | None = None
    images_processed: int = 0
    started_at: UTCDateTime
    finished_at: UTCDateTime | None
    started_by_name: str | None
    model_name: str
    model_version: str
    thresholds: dict | None
    image_count: int
    faces_detected: int
    confident_count: int
    low_confidence_count: int
    ambiguous_count: int
    duplicate_count: int
    unknown_count: int
    students_recognized: int
    roster_size: int
    eligible_count: int
    applied_count: int
    preserved_count: int
    missing_students: list[StudentRef]  # on the roster but cannot be recognised automatically
    warnings: list[str]
    # model/detector actually used (incl. fallback), detection passes, timings — never vectors
    diagnostics: dict | None = None
    error_message: str | None
    is_latest: bool


class RecognitionOut(BaseModel):
    run: RecognitionRunOut | None
    faces: list[RecognitionFaceOut]
    can_run: bool
    can_decide: bool


class RecognitionActionOut(BaseModel):
    recognition: RecognitionOut
    session: SessionDetail


class RunRequest(BaseModel):
    version: int


class FaceDecisionRequest(BaseModel):
    version: int


class FaceAssignRequest(BaseModel):
    version: int
    student_id: int
    replace: bool = False  # True = take the student away from the face it is currently linked to
