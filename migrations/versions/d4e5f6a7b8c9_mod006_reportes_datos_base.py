"""mod006 reportes datos base

Revision ID: d4e5f6a7b8c9
Revises: c2a9de4f61b2
Create Date: 2026-04-11 18:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c2a9de4f61b2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    usuario_columns = {col["name"] for col in inspector.get_columns("usuarios")}
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        if "fuente_captacion" not in usuario_columns:
            batch_op.add_column(
                sa.Column(
                    "fuente_captacion",
                    sa.Enum("recomendacion", "redes_sociales", name="fuente_captacion_cliente"),
                    nullable=True,
                )
            )
        if "fecha_registro" not in usuario_columns:
            batch_op.add_column(
                sa.Column(
                    "fecha_registro",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
            )

    insumo_columns = {col["name"] for col in inspector.get_columns("insumos_clinicos")}
    with op.batch_alter_table("insumos_clinicos", schema=None) as batch_op:
        if "precio" not in insumo_columns:
            batch_op.add_column(
                sa.Column("precio", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0.00"))
            )

    analisis_columns = {col["name"] for col in inspector.get_columns("analisis_clinicos")}
    with op.batch_alter_table("analisis_clinicos", schema=None) as batch_op:
        if "precio" not in analisis_columns:
            batch_op.add_column(
                sa.Column("precio", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0.00"))
            )

    consultas_columns = {col["name"] for col in inspector.get_columns("consultas_medicas")}
    with op.batch_alter_table("consultas_medicas", schema=None) as batch_op:
        if "vacuna_insumo_id" not in consultas_columns:
            batch_op.add_column(sa.Column("vacuna_insumo_id", sa.Integer(), nullable=True))
        if "tipo_analisis_relacionado" not in consultas_columns:
            batch_op.add_column(sa.Column("tipo_analisis_relacionado", sa.String(length=120), nullable=True))
        if "precio_consulta" not in consultas_columns:
            batch_op.add_column(
                sa.Column("precio_consulta", sa.Numeric(10, 2), nullable=False, server_default=sa.text("300.00"))
            )

    inspector = sa.inspect(bind)
    consultas_columns = {col["name"] for col in inspector.get_columns("consultas_medicas")}
    consultas_fks = {
        fk["constrained_columns"][0]
        for fk in inspector.get_foreign_keys("consultas_medicas")
        if fk["constrained_columns"]
    }

    with op.batch_alter_table("consultas_medicas", schema=None) as batch_op:
        if "vacuna_insumo_id" in consultas_columns and "vacuna_insumo_id" not in consultas_fks:
            batch_op.create_foreign_key(
                "fk_consultas_medicas_vacuna_insumo",
                "insumos_clinicos",
                ["vacuna_insumo_id"],
                ["id"],
            )


def downgrade():
    with op.batch_alter_table("consultas_medicas", schema=None) as batch_op:
        batch_op.drop_constraint("fk_consultas_medicas_vacuna_insumo", type_="foreignkey")
        batch_op.drop_column("precio_consulta")
        batch_op.drop_column("tipo_analisis_relacionado")
        batch_op.drop_column("vacuna_insumo_id")

    with op.batch_alter_table("analisis_clinicos", schema=None) as batch_op:
        batch_op.drop_column("precio")

    with op.batch_alter_table("insumos_clinicos", schema=None) as batch_op:
        batch_op.drop_column("precio")

    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.drop_column("fecha_registro")
        batch_op.drop_column("fuente_captacion")
