"""mod005 expedientes clinicos

Revision ID: b1d2f44a8f10
Revises: a5b9f7c2d1e3
Create Date: 2026-04-10 18:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1d2f44a8f10"
down_revision = "c8a4b3d9e2f1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("consultas_medicas"):
        op.create_table(
            "consultas_medicas",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mascota_id", sa.Integer(), nullable=False),
            sa.Column("veterinario_id", sa.Integer(), nullable=False),
            sa.Column("fecha_consulta", sa.Date(), nullable=False),
            sa.Column("sintomas", sa.Text(), nullable=False),
            sa.Column("diagnostico", sa.Text(), nullable=False),
            sa.Column("tratamiento", sa.Text(), nullable=False),
            sa.Column("medicamentos_administrados", sa.Text(), nullable=True),
            sa.Column("observaciones", sa.Text(), nullable=True),
            sa.Column("fecha_creacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("fecha_actualizacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["mascota_id"], ["mascotas.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["veterinario_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("vacunas_alergias"):
        op.create_table(
            "vacunas_alergias",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mascota_id", sa.Integer(), nullable=False),
            sa.Column("veterinario_id", sa.Integer(), nullable=False),
            sa.Column("tipo_registro", sa.Enum("vacuna", "alergia", name="tipo_registro_clinico"), nullable=False),
            sa.Column("fecha_registro", sa.Date(), nullable=False),
            sa.Column("nombre", sa.String(length=120), nullable=False),
            sa.Column("reaccion_identificada", sa.Text(), nullable=True),
            sa.Column("notas_adicionales", sa.Text(), nullable=True),
            sa.Column("fecha_creacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("fecha_actualizacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["mascota_id"], ["mascotas.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["veterinario_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("analisis_clinicos"):
        op.create_table(
            "analisis_clinicos",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mascota_id", sa.Integer(), nullable=False),
            sa.Column("veterinario_id", sa.Integer(), nullable=False),
            sa.Column("fecha_analisis", sa.Date(), nullable=False),
            sa.Column("tipo_analisis", sa.String(length=120), nullable=False),
            sa.Column("resultados", sa.Text(), nullable=False),
            sa.Column("documentos_adjuntos", sa.Text(), nullable=True),
            sa.Column("fecha_creacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("fecha_actualizacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["mascota_id"], ["mascotas.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["veterinario_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    op.drop_table("analisis_clinicos")
    op.drop_table("vacunas_alergias")
    op.drop_table("consultas_medicas")
