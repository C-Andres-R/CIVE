"""mod005 revertir nombre de vacunas_alergias a 120

Revision ID: 9a2c1e7d4b55
Revises: 5e1b7c9a2d44
Create Date: 2026-05-08 23:48:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9a2c1e7d4b55"
down_revision = "5e1b7c9a2d44"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vacunas_alergias", schema=None) as batch_op:
        batch_op.alter_column(
            "nombre",
            existing_type=sa.String(length=300),
            type_=sa.String(length=120),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table("vacunas_alergias", schema=None) as batch_op:
        batch_op.alter_column(
            "nombre",
            existing_type=sa.String(length=120),
            type_=sa.String(length=300),
            existing_nullable=False,
        )
