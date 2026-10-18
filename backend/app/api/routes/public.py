"""Unauthenticated read-only data needed by the student registration form."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.auth.dependencies import DbSession
from backend.app.models import Batch, Department, Semester
from backend.app.schemas.academic import (
    BatchOption,
    DepartmentTree,
    SectionOption,
    SemesterOption,
)

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/academic-structure", response_model=list[DepartmentTree])
def academic_structure(db: DbSession):
    departments = db.scalars(
        select(Department)
        .where(Department.is_active.is_(True))
        .options(
            selectinload(Department.batches)
            .selectinload(Batch.semesters)
            .selectinload(Semester.sections)
        )
        .order_by(Department.name)
    ).all()
    return [
        DepartmentTree(
            id=d.id,
            label=d.name,
            code=d.code,
            batches=[
                BatchOption(
                    id=b.id,
                    label=b.name,
                    semesters=[
                        SemesterOption(
                            id=s.id,
                            label=f"Semester {s.number}",
                            number=s.number,
                            sections=[SectionOption(id=x.id, label=x.name) for x in sorted(s.sections, key=lambda x: x.name)],
                        )
                        for s in sorted(b.semesters, key=lambda s: s.number)
                    ],
                )
                for b in d.batches
                if b.is_active
            ],
        )
        for d in departments
    ]
