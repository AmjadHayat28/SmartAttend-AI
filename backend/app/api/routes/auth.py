from fastapi import APIRouter, Body, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from backend.app.auth.dependencies import CurrentUser, DbSession
from backend.app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    OnboardingTokenResponse,
    RefreshRequest,
    StudentRegisterRequest,
    TokenResponse,
    UserProfile,
)
from backend.app.core.config import settings
from backend.app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# Refreshing with the cookie needs this header too. Browsers only add custom headers to
# cross-site requests after a CORS preflight that a foreign origin fails — CSRF defence in depth
# on top of SameSite=strict.
REFRESH_HEADER, REFRESH_HEADER_VALUE = "X-Requested-With", "SmartClass"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE, token, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=settings.refresh_cookie_path, httponly=True, secure=settings.refresh_cookie_secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(settings.AUTH_REFRESH_COOKIE, path=settings.refresh_cookie_path, httponly=True,
                           secure=settings.refresh_cookie_secure, samesite=settings.AUTH_COOKIE_SAMESITE)


def _cookie_only(tokens: TokenResponse, response: Response) -> TokenResponse:
    """Put the refresh token in the HttpOnly cookie and keep it out of the JSON body."""
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens.model_copy(update={"refresh_token": None})


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, request: Request, response: Response, db: DbSession):
    """Single login endpoint for all roles; the role is carried in the token and profile.
    The access token is returned in the body; the refresh token only as an HttpOnly cookie."""
    return _cookie_only(auth_service.login(db, data, request), response)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: DbSession, data: RefreshRequest | None = Body(None)):
    """New access token (and a renewed refresh cookie) from the refresh cookie. A refresh token in
    the body is accepted for sessions created before the cookie existed; it moves them onto it."""
    token = request.cookies.get(settings.AUTH_REFRESH_COOKIE)
    if token:
        if request.headers.get(REFRESH_HEADER) != REFRESH_HEADER_VALUE:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing request header.")
    elif data is not None and data.refresh_token:
        token = data.refresh_token
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        return _cookie_only(auth_service.refresh(db, token), response)
    except HTTPException as exc:
        failed = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        _clear_refresh_cookie(failed)  # a dead cookie is removed so the browser stops sending it
        return failed


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout():
    """Remove the refresh cookie (this browser only). The short-lived access token is discarded by
    the client; to end every session at once, change the password."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.post("/register/student", response_model=OnboardingTokenResponse, status_code=status.HTTP_201_CREATED)
def register_student(data: StudentRegisterRequest, request: Request, db: DbSession):
    """Public student self-registration. Accounts start as PENDING until approved.
    Teachers/HODs have no public registration — they are created by admins.

    The response carries a short-lived onboarding token so the student can continue straight
    to profile-photo and face-enrollment upload (the only endpoints it is valid for)."""
    user = auth_service.register_student(db, data, request)
    return OnboardingTokenResponse(
        message="Registration submitted. Add your photos now; you can sign in once your account is approved.",
        onboarding_token=auth_service.issue_onboarding_token(user),
        expires_in=settings.ONBOARDING_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/onboarding-token", response_model=OnboardingTokenResponse)
def onboarding_token(data: LoginRequest, request: Request, db: DbSession):
    """For pending students returning to finish their enrollment photos."""
    token = auth_service.onboarding_login(db, data, request)
    return OnboardingTokenResponse(message="Continue your photo enrollment.", onboarding_token=token,
                                   expires_in=settings.ONBOARDING_TOKEN_EXPIRE_MINUTES * 60)


@router.get("/me", response_model=UserProfile)
def me(user: CurrentUser, db: DbSession):
    return auth_service.build_profile(db, user)


@router.post("/change-password", response_model=MessageResponse)
def change_password(data: ChangePasswordRequest, request: Request, user: CurrentUser, db: DbSession):
    auth_service.change_password(db, user, data, request)
    return MessageResponse(message="Password changed. Please log in again.")
