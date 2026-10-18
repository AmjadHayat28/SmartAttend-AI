from fastapi import APIRouter

from backend.app.api.routes import academics, accounts, attendance, auth, dashboard, departments, enrollments, face, people, public, reports, student

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(public.router)
api_router.include_router(departments.router)
api_router.include_router(accounts.router)
api_router.include_router(dashboard.router)
api_router.include_router(academics.router)
api_router.include_router(people.router)
api_router.include_router(enrollments.router)
api_router.include_router(face.router)
api_router.include_router(attendance.router)
api_router.include_router(student.router)
api_router.include_router(reports.router)
