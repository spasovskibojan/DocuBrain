"""Drop documents.original_filename

Revision ID: a3c1f0d2b7e4
Revises: 569ea2f38cea
Create Date: 2026-11-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a3c1f0d2b7e4'
down_revision: Union[str, Sequence[str], None] = '569ea2f38cea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('documents', 'original_filename')


def downgrade() -> None:
    op.add_column('documents', sa.Column('original_filename', sa.String(length=255), nullable=True))
    op.execute("UPDATE documents SET original_filename = filename")
    op.alter_column('documents', 'original_filename', nullable=False)
