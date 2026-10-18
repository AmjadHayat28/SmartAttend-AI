from fastapi import APIRouter, Query, Request

from backend.app.auth.dependencies import AdminOrHod, HodUser, DbSession
from backend.app.schemas.auth import MessageResponse
from backend.app.schemas.common import PasswordReset
from backend.app.schemas.user import AccountStatusUpdate, Page, PendingStudentOut, UserListItem
from backend.app.services import account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/pending-students", response_model=Page[PendingStudentOut])
def pending_students(
    actor: HodUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return account_service.list_pending_students(db, actor, page, page_size)


@router.patch("/{user_id}/status", response_model=UserListItem)
def update_status(user_id: int, data: AccountStatusUpdate, request: Request, actor: AdminOrHod, db: DbSession):
    """Approve / reject / suspend / reactivate. HODs may only manage teachers and students
    of their own department; only the super admin manages HOD accounts."""
    return account_service.update_account_status(db, actor, user_id, data, request)


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
def reset_password(user_id: int, data: PasswordReset, request: Request, actor: AdminOrHod, db: DbSession):
    """Set a new password for a managed account. All of that user's sessions are revoked."""
    account_service.reset_password(db, actor, user_id, data.new_password, request)
    return MessageResponse(message="Password reset. The user must sign in with the new password.")
