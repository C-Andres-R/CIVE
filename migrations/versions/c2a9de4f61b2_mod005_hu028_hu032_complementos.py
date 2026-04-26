"""mod005 hu028 hu032 complementos

Revision ID: c2a9de4f61b2
Revises: b1d2f44a8f10
Create Date: 2026-04-11 15:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c2a9de4f61b2"
down_revision = "b1d2f44a8f10"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("insumos_clinicos"):
        op.create_table(
            "insumos_clinicos",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nombre", sa.String(length=120), nullable=False),
            sa.Column("tipo_insumo", sa.Enum("medicamento", "vacuna", name="tipo_insumo_clinico"), nullable=False),
            sa.Column("fecha_caducidad", sa.Date(), nullable=False),
            sa.Column("cantidad_existencia", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("fecha_creacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("fecha_actualizacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
        )

    consultas_columns = {col["name"] for col in inspector.get_columns("consultas_medicas")}
    with op.batch_alter_table("consultas_medicas", schema=None) as batch_op:
        if "insumo_clinico_id" not in consultas_columns:
            batch_op.add_column(sa.Column("insumo_clinico_id", sa.Integer(), nullable=True))
        if "fecha_administracion" not in consultas_columns:
            batch_op.add_column(sa.Column("fecha_administracion", sa.Date(), nullable=True))
        if "dosis" not in consultas_columns:
            batch_op.add_column(sa.Column("dosis", sa.String(length=120), nullable=True))
        if "periodo_administracion" not in consultas_columns:
            batch_op.add_column(sa.Column("periodo_administracion", sa.String(length=120), nullable=True))

    vacunas_columns = {col["name"] for col in inspector.get_columns("vacunas_alergias")}
    with op.batch_alter_table("vacunas_alergias", schema=None) as batch_op:
        if "insumo_clinico_id" not in vacunas_columns:
            batch_op.add_column(sa.Column("insumo_clinico_id", sa.Integer(), nullable=True))

    analisis_columns = {col["name"] for col in inspector.get_columns("analisis_clinicos")}
    with op.batch_alter_table("analisis_clinicos", schema=None) as batch_op:
        if "archivo_adjunto" not in analisis_columns:
            batch_op.add_column(sa.Column("archivo_adjunto", sa.Text(), nullable=True))
        if "nombre_archivo" not in analisis_columns:
            batch_op.add_column(sa.Column("nombre_archivo", sa.String(length=255), nullable=True))

    inspector = sa.inspect(bind)
    consultas_fks = {fk["constrained_columns"][0] for fk in inspector.get_foreign_keys("consultas_medicas") if fk["constrained_columns"]}
    vacunas_fks = {fk["constrained_columns"][0] for fk in inspector.get_foreign_keys("vacunas_alergias") if fk["constrained_columns"]}

    with op.batch_alter_table("consultas_medicas", schema=None) as batch_op:
        if "insumo_clinico_id" in {col["name"] for col in inspector.get_columns("consultas_medicas")} and "insumo_clinico_id" not in consultas_fks:
            batch_op.create_foreign_key(
                "fk_consultas_medicas_insumo_clinico",
                "insumos_clinicos",
                ["insumo_clinico_id"],
                ["id"],
            )

    with op.batch_alter_table("vacunas_alergias", schema=None) as batch_op:
        if "insumo_clinico_id" in {col["name"] for col in inspector.get_columns("vacunas_alergias")} and "insumo_clinico_id" not in vacunas_fks:
            batch_op.create_foreign_key(
                "fk_vacunas_alergias_insumo_clinico",
                "insumos_clinicos",
                ["insumo_clinico_id"],
                ["id"],
            )


def downgrade():
    with op.batch_alter_table("analisis_clinicos", schema=None) as batch_op:
        batch_op.drop_column("nombre_archivo")
        batch_op.drop_column("archivo_adjunto")

    with op.batch_alter_table("vacunas_alergias", schema=None) as batch_op:
        batch_op.drop_constraint("fk_vacunas_alergias_insumo_clinico", type_="foreignkey")
        batch_op.drop_column("insumo_clinico_id")

    with op.batch_alter_table("consultas_medicas", schema=None) as batch_op:
        batch_op.drop_constraint("fk_consultas_medicas_insumo_clinico", type_="foreignkey")
        batch_op.drop_column("periodo_administracion")
        batch_op.drop_column("dosis")
        batch_op.drop_column("fecha_administracion")
        batch_op.drop_column("insumo_clinico_id")

    op.drop_table("insumos_clinicos")
