"""recognition diagnostics

Phase 8:
- attendance_recognition_runs.diagnostics: non-sensitive run metadata (model and detector actually
  used, fallback, detection passes/tiles, merged duplicate boxes, timings). No vectors, no pixels.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('attendance_recognition_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'diagnostics', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('attendance_recognition_runs', schema=None) as batch_op:
        batch_op.drop_column('diagnostics')
