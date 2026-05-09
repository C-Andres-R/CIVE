"""mod005 ampliar nombre de vacunas_alergias a 300

Revision ID: 5e1b7c9a2d44
Revises: 1b7e2c3d4f50
Create Date: 2026-05-08 22:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "5e1b7c9a2d44"
down_revision = "1b7e2c3d4f50"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vacunas_alergias", schema=None) as batch_op:
        batch_op.alter_column(
            "nombre",
            existing_type=sa.String(length=120),
            type_=sa.String(length=300),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table("vacunas_alergias", schema=None) as batch_op:
        batch_op.alter_column(
            "nombre",
            existing_type=sa.String(length=300),
            type_=sa.String(length=120),
            existing_nullable=False,
        )
