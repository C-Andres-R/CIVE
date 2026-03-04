"""mod006 normalizacion clientes

Revision ID: a5b9f7c2d1e3
Revises: 7cfd9d3c7a21
Create Date: 2026-03-04 12:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a5b9f7c2d1e3"
down_revision = "7cfd9d3c7a21"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nombres", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("apellido_paterno", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("apellido_materno", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("calle", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("numero", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("colonia", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("codigo_postal", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("estado", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("entidad", sa.String(length=80), nullable=True))

    # Preserva datos previos para transicionar sin perder registros.
    op.execute("UPDATE usuarios SET nombres = nombre WHERE (nombres IS NULL OR nombres = '') AND nombre IS NOT NULL")
    op.execute("UPDATE usuarios SET calle = domicilio WHERE (calle IS NULL OR calle = '') AND domicilio IS NOT NULL")


def downgrade():
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.drop_column("entidad")
        batch_op.drop_column("estado")
        batch_op.drop_column("codigo_postal")
        batch_op.drop_column("colonia")
        batch_op.drop_column("numero")
        batch_op.drop_column("calle")
        batch_op.drop_column("apellido_materno")
        batch_op.drop_column("apellido_paterno")
        batch_op.drop_column("nombres")
