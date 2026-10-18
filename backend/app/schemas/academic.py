from datetime import date
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from backend.app.schemas.common import BatchName, CourseCode, SectionName, Title


def _strip_or_none(value: object) -> object:
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


class DepartmentBase(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=2000)


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class DepartmentOut(DepartmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool


class OptionOut(BaseModel):
    """Lightweight id/label pair for dropdowns."""

    id: int
    label: str


class SectionOption(OptionOut):
    pass


class SemesterOption(OptionOut):
    number: int
    sections: list[SectionOption]


class BatchOption(OptionOut):
    semesters: list[SemesterOption]


class DepartmentTree(OptionOut):
    code: str
    batches: list[BatchOption]


# ── Management (Phase 3) ────────────────────────────────────────────────────


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BatchCreate(BaseModel):
    name: BatchName
    start_year: int = Field(ge=1990, le=2100)
    end_year: int | None = Field(default=None, ge=1990, le=2100)
    department_id: int | None = None  # required for super admin; ignored/forced for HOD
    is_active: bool = True

    @model_validator(mode="after")
    def check_years(self):
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year cannot be before start_year")
        return self


class BatchUpdate(BaseModel):
    name: BatchName | None = None
    start_year: int | None = Field(default=None, ge=1990, le=2100)
    end_year: int | None = Field(default=None, ge=1990, le=2100)
    is_active: bool | None = None


class BatchOut(_Out):
    id: int
    department_id: int
    department_code: str
    name: str
    start_year: int
    end_year: int | None
    is_active: bool
    semester_count: int = 0
    student_count: int = 0


class SemesterCreate(BaseModel):
    batch_id: int
    number: int = Field(ge=1, le=12)
    name: Annotated[Annotated[str, Field(max_length=50)] | None, BeforeValidator(_strip_or_none)] = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def check_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class SemesterUpdate(BaseModel):
    number: int | None = Field(default=None, ge=1, le=12)
    name: Annotated[Annotated[str, Field(min_length=1, max_length=50)] | None, BeforeValidator(_strip_or_none)] = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    is_active: bool | None = None


class SemesterOut(_Out):
    id: int
    batch_id: int
    batch_name: str
    department_id: int
    department_code: str
    number: int
    name: str
    start_date: date | None
    end_date: date | None
    is_current: bool
    is_active: bool
    section_count: int = 0


class SectionCreate(BaseModel):
    semester_id: int
    # Optional consistency checks: when sent, they must match the semester's chain.
    batch_id: int | None = None
    department_id: int | None = None
    name: SectionName
    capacity: int | None = Field(default=None, ge=1, le=1000)
    is_active: bool = True


class SectionUpdate(BaseModel):
    name: SectionName | None = None
    capacity: int | None = Field(default=None, ge=1, le=1000)
    is_active: bool | None = None


class SectionOut(_Out):
    id: int
    name: str
    capacity: int | None
    is_active: bool
    semester_id: int
    semester_number: int
    semester_name: str
    batch_id: int
    batch_name: str
    department_id: int
    department_code: str
    student_count: int = 0


class CourseCreate(BaseModel):
    code: CourseCode
    title: Title
    credit_hours: int = Field(default=3, ge=0, le=10)
    is_lab: bool = False
    semester_number: int | None = Field(default=None, ge=1, le=12)
    department_id: int | None = None
    is_active: bool = True


class CourseUpdate(BaseModel):
    code: CourseCode | None = None
    title: Title | None = None
    credit_hours: int | None = Field(default=None, ge=0, le=10)
    is_lab: bool | None = None
    semester_number: int | None = Field(default=None, ge=1, le=12)
    is_active: bool | None = None


class CourseOut(_Out):
    id: int
    department_id: int
    department_code: str
    code: str
    title: str
    credit_hours: int
    is_lab: bool
    semester_number: int | None
    is_active: bool


class StructureSection(BaseModel):
    id: int
    name: str
    is_active: bool


class StructureSemester(BaseModel):
    id: int
    number: int
    name: str
    is_active: bool
    is_current: bool
    sections: list[StructureSection]


class StructureBatch(BaseModel):
    id: int
    name: str
    is_active: bool
    semesters: list[StructureSemester]


class StructureDepartment(BaseModel):
    id: int
    name: str
    code: str
    is_active: bool
    batches: list[StructureBatch]
