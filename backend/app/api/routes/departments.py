from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, or_, select

from backend.app.auth.dependencies import AdminUser, CurrentUser, DbSession, ensure_department_access, scoped_department_id
from backend.app.models import Department
from backend.app.schemas.academic import DepartmentCreate, DepartmentOut, DepartmentUpdate
from backend.app.services.audit_service import record_audit

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=list[DepartmentOut])
def list_departments(user: CurrentUser, db: DbSession):
    """Super admin sees all departments; everyone else sees only their own."""
    stmt = select(Department).order_by(Department.name)
    scope = scoped_department_id(user)
    if scope is not None:
        stmt = stmt.where(Department.id == scope)
    return db.scalars(stmt).all()


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(department_id: int, user: CurrentUser, db: DbSession):
    ensure_department_access(user, department_id)
    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    return department


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(data: DepartmentCreate, request: Request, admin: AdminUser, db: DbSession):
    code = data.code.upper()
    clash = db.scalar(
        select(Department.id).where(
            or_(func.lower(Department.name) == data.name.lower(), Department.code == code)
        )
    )
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Department name or code already exists")
    department = Department(name=data.name.strip(), code=code, description=data.description)
    db.add(department)
    db.flush()
    record_audit(db, actor=admin, action="department.created", entity="department",
                 entity_id=department.id, department_id=department.id,
                 new_value=data.model_dump(), request=request)
    db.commit()
    return department


@router.patch("/{department_id}", response_model=DepartmentOut)
def update_department(department_id: int, data: DepartmentUpdate, request: Request, admin: AdminUser, db: DbSession):
    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    changes = data.model_dump(exclude_unset=True)
    old = {key: getattr(department, key) for key in changes}
    for key, value in changes.items():
        setattr(department, key, value)
    record_audit(db, actor=admin, action="department.updated", entity="department",
                 entity_id=department.id, department_id=department.id,
                 old_value=old, new_value=changes, request=request)
    db.commit()
    return department
