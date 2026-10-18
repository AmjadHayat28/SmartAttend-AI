"""Write the PostgreSQL DDL for all models to database/schema.sql.

Run with:  uv run python -m backend.app.scripts.export_schema
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from backend.app import models  # noqa: F401  (register models)
from backend.app.core.config import PROJECT_ROOT
from backend.app.database.base import Base

HEADER = """-- SmartClass AI Attendance — PostgreSQL schema
-- GENERATED from SQLAlchemy models by backend/app/scripts/export_schema.py. Do not edit by hand.
-- Apply with: psql -U smartclass -d smartclass_db -f database/schema.sql
-- (or let the app create tables: uv run python -m backend.app.database.init_db)

"""


def main() -> None:
    dialect = postgresql.dialect()
    parts = [HEADER]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";\n")
        parts.append("\n")
    out = PROJECT_ROOT / "database" / "schema.sql"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
