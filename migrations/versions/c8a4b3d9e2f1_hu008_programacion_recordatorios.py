"""hu008 programacion recordatorios

Revision ID: c8a4b3d9e2f1
Revises: 7cfd9d3c7a21
Create Date: 2026-03-23 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c8a4b3d9e2f1"
down_revision = "a5b9f7c2d1e3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recordatorios_citas", sa.Column("anticipacion_horas", sa.Integer(), nullable=True))
    op.add_column("recordatorios_citas", sa.Column("programado_para", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("recordatorios_citas", "programado_para")
    op.drop_column("recordatorios_citas", "anticipacion_horas")
