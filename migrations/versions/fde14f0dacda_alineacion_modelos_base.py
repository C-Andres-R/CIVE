"""alineacion modelos base

Revision ID: fde14f0dacda
Revises:
Create Date: 2026-01-27 16:28:43.437512

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "fde14f0dacda"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Esta revision ahora funciona como baseline coherente para una base nueva.
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
    )

    op.create_table(
        "permisos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
    )

    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("correo", sa.String(length=255), nullable=False),
        sa.Column("contrasena", sa.String(length=255), nullable=False),
        sa.Column("telefono", sa.String(length=20), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("eliminado", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("rol_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["rol_id"], ["roles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("correo"),
    )

    op.create_table(
        "roles_permisos",
        sa.Column("rol_id", sa.Integer(), nullable=False),
        sa.Column("permiso_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["permiso_id"], ["permisos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rol_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rol_id", "permiso_id"),
    )

    op.create_table(
        "mascotas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("fecha_nacimiento", sa.Date(), nullable=False),
        sa.Column("peso", sa.Float(), nullable=True),
        sa.Column("raza", sa.String(length=100), nullable=True),
        sa.Column("especie", sa.Enum("perro", "gato", "otro", name="especie_mascota"), nullable=False),
        sa.Column("sexo", sa.Enum("macho", "hembra", name="sexo_mascota"), nullable=False),
        sa.Column("datos_adicionales", sa.Text(), nullable=True),
        sa.Column(
            "estado",
            sa.Enum("activa", "inactiva", name="estado_mascota"),
            nullable=False,
            server_default=sa.text("'activa'"),
        ),
        sa.Column("razon_inactivacion", sa.Text(), nullable=True),
        sa.Column("dueno_id", sa.Integer(), nullable=False),
        sa.Column("comportamiento", sa.Text(), nullable=True),
        sa.Column("fecha_registro", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("fecha_actualizacion", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["dueno_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "citas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fecha_hora", sa.DateTime(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("veterinario_id", sa.Integer(), nullable=False),
        sa.Column("mascota_id", sa.Integer(), nullable=False),
        sa.Column(
            "estado",
            sa.Enum("pendiente", "confirmada", "cancelada", name="estado_cita"),
            nullable=False,
            server_default=sa.text("'pendiente'"),
        ),
        sa.Column("cancelada", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("fecha_creacion", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["mascota_id"], ["mascotas.id"]),
        sa.ForeignKeyConstraint(["veterinario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("citas")
    op.drop_table("mascotas")
    op.drop_table("roles_permisos")
    op.drop_table("usuarios")
    op.drop_table("permisos")
    op.drop_table("roles")
