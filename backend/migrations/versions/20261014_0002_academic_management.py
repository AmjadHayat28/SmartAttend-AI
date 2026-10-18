"""academic management

Phase 3:
- hods: one *current* HOD per department (partial unique index) instead of one HOD row
  per department forever, so a department's HOD can be replaced while history is kept.
- semesters: human-readable name + active flag.
- sections: active flag.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 14:28:37.391299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('hods', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_current', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.drop_constraint(batch_op.f('uq_hods_department_id'), type_='unique')
        batch_op.create_index(batch_op.f('ix_hods_department_id'), ['department_id'], unique=False)
        batch_op.create_index('uq_hods_current_department', ['department_id'], unique=True,
                              postgresql_where=sa.text('is_current'), sqlite_where=sa.text('is_current'))

    with op.batch_alter_table('sections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False))

    # Add semesters.name as nullable, backfill existing rows, then enforce NOT NULL.
    with op.batch_alter_table('semesters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.execute("UPDATE semesters SET name = 'Semester ' || CAST(number AS VARCHAR) WHERE name IS NULL")
    with op.batch_alter_table('semesters', schema=None) as batch_op:
        batch_op.alter_column('name', existing_type=sa.String(length=50), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    history = bind.execute(sa.text("SELECT COUNT(*) FROM hods WHERE NOT is_current")).scalar()
    if history:
        raise RuntimeError(
            f"Cannot downgrade: {history} former-HOD row(s) exist and revision 0001 allows only "
            "one HOD row per department. Remove or archive them first."
        )

    with op.batch_alter_table('semesters', schema=None) as batch_op:
        batch_op.drop_column('is_active')
        batch_op.drop_column('name')

    with op.batch_alter_table('sections', schema=None) as batch_op:
        batch_op.drop_column('is_active')

    with op.batch_alter_table('hods', schema=None) as batch_op:
        batch_op.drop_index('uq_hods_current_department', postgresql_where=sa.text('is_current'),
                            sqlite_where=sa.text('is_current'))
        batch_op.drop_index(batch_op.f('ix_hods_department_id'))
        batch_op.create_unique_constraint(batch_op.f('uq_hods_department_id'), ['department_id'])
        batch_op.drop_column('is_current')
