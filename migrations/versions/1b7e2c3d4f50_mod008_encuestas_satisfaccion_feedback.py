"""mod008 encuestas satisfaccion feedback

Revision ID: 1b7e2c3d4f50
Revises: d4e5f6a7b8c9
Create Date: 2026-04-12 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1b7e2c3d4f50"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("encuestas_satisfaccion"):
        columns = {column["name"] for column in inspector.get_columns("encuestas_satisfaccion")}

        with op.batch_alter_table("encuestas_satisfaccion") as batch_op:
            if "calificacion" in columns:
                batch_op.alter_column(
                    "calificacion",
                    existing_type=sa.Integer(),
                    nullable=True,
                )
            if "fecha_envio" in columns:
                batch_op.alter_column(
                    "fecha_envio",
                    existing_type=sa.DateTime(),
                    nullable=True,
                    server_default=None,
                )
            if "respondido" in columns:
                batch_op.alter_column(
                    "respondido",
                    existing_type=sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            if "conforme" not in columns:
                batch_op.add_column(sa.Column("conforme", sa.Boolean(), nullable=True))
            if "detalle_inconformidad" not in columns:
                batch_op.add_column(sa.Column("detalle_inconformidad", sa.String(length=300), nullable=True))
            if "fecha_programada_envio" not in columns:
                batch_op.add_column(sa.Column("fecha_programada_envio", sa.DateTime(), nullable=True))
            if "fecha_respuesta" not in columns:
                batch_op.add_column(sa.Column("fecha_respuesta", sa.DateTime(), nullable=True))
            if "correo_enviado" not in columns:
                batch_op.add_column(
                    sa.Column("correo_enviado", sa.Boolean(), nullable=False, server_default=sa.text("0"))
                )

        op.execute(
            sa.text(
                "UPDATE encuestas_satisfaccion "
                "SET respondido = 1 "
                "WHERE calificacion IS NOT NULL"
            )
        )
        op.execute(
            sa.text(
                "UPDATE encuestas_satisfaccion "
                "SET correo_enviado = 1 "
                "WHERE fecha_envio IS NOT NULL"
            )
        )

    else:
        op.create_table(
            "encuestas_satisfaccion",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cita_id", sa.Integer(), nullable=False),
            sa.Column("cliente_id", sa.Integer(), nullable=False),
            sa.Column("calificacion", sa.Integer(), nullable=True),
            sa.Column("conforme", sa.Boolean(), nullable=True),
            sa.Column("detalle_inconformidad", sa.String(length=300), nullable=True),
            sa.Column("comentario", sa.Text(), nullable=True),
            sa.Column("fecha_programada_envio", sa.DateTime(), nullable=True),
            sa.Column("fecha_envio", sa.DateTime(), nullable=True),
            sa.Column("fecha_respuesta", sa.DateTime(), nullable=True),
            sa.Column("correo_enviado", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("respondido", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.CheckConstraint("calificacion >= 1 AND calificacion <= 5", name="ck_encuestas_calificacion_1_5"),
            sa.ForeignKeyConstraint(["cita_id"], ["citas.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["cliente_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cita_id", "cliente_id", name="uq_encuestas_cita_cliente"),
        )

    if not inspector.has_table("encuestas_preguntas"):
        op.create_table(
            "encuestas_preguntas",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("clave", sa.String(length=80), nullable=False),
            sa.Column("texto", sa.String(length=255), nullable=False),
            sa.Column("fecha_actualizacion", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("clave", name="uq_encuestas_preguntas_clave"),
        )


def downgrade():
    if op.get_bind().dialect.has_table(op.get_bind(), "encuestas_preguntas"):
        op.drop_table("encuestas_preguntas")

    if op.get_bind().dialect.has_table(op.get_bind(), "encuestas_satisfaccion"):
        with op.batch_alter_table("encuestas_satisfaccion") as batch_op:
            for column_name in (
                "correo_enviado",
                "fecha_respuesta",
                "fecha_programada_envio",
                "detalle_inconformidad",
                "conforme",
            ):
                existing_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("encuestas_satisfaccion")}
                if column_name in existing_columns:
                    batch_op.drop_column(column_name)
            batch_op.alter_column(
                "calificacion",
                existing_type=sa.Integer(),
                nullable=False,
            )
            batch_op.alter_column(
                "fecha_envio",
                existing_type=sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
            batch_op.alter_column(
                "respondido",
                existing_type=sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            )
