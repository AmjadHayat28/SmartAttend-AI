"""recognition progress and single-run guard

Phase 9:
- attendance_recognition_runs.stage / images_processed: the step a running recognition is on
  (detecting / matching / saving) and photos done, for a truthful progress display.
- uq_recognition_runs_one_processing: at most one PROCESSING run per session (partial unique
  index), so concurrent "Run" requests cannot both start.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('attendance_recognition_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stage', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('images_processed', sa.Integer(), server_default='0', nullable=False))
    # No server is running during a migration, so any run still "processing" was interrupted.
    # (Also makes the unique index below safe to create.)
    op.execute("UPDATE attendance_recognition_runs SET status = 'failed', "
               "error_message = 'Interrupted. Attendance was not changed.' WHERE status = 'processing'")
    op.create_index(
        'uq_recognition_runs_one_processing', 'attendance_recognition_runs', ['session_id'], unique=True,
        postgresql_where=sa.text("status = 'processing'"), sqlite_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index('uq_recognition_runs_one_processing', table_name='attendance_recognition_runs')
    with op.batch_alter_table('attendance_recognition_runs', schema=None) as batch_op:
        batch_op.drop_column('images_processed')
        batch_op.drop_column('stage')
