"""shared login rate limiting

Phase 11:
- login_attempts: one row per failed login (SHA-256 of "ip:email" + time), so the login rate
  limit is shared by every uvicorn worker and survives restarts. Rows older than the rate-limit
  window are deleted automatically by the application.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'login_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts')),
    )
    op.create_index(op.f('ix_login_attempts_key_hash'), 'login_attempts', ['key_hash'], unique=False)
    op.create_index(op.f('ix_login_attempts_attempted_at'), 'login_attempts', ['attempted_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_login_attempts_attempted_at'), table_name='login_attempts')
    op.drop_index(op.f('ix_login_attempts_key_hash'), table_name='login_attempts')
    op.drop_table('login_attempts')
