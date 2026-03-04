"""mod005 chat multimedia support

Revision ID: 7cfd9d3c7a21
Revises: 0f3a9b2d1c44
Create Date: 2026-03-03 22:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7cfd9d3c7a21"
down_revision = "0f3a9b2d1c44"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("chatbot_faq"):
        op.create_table(
            "chatbot_faq",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pregunta", sa.String(length=255), nullable=False),
            sa.Column("respuesta", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("pregunta"),
        )

    if not inspector.has_table("encuestas_satisfaccion"):
        op.create_table(
            "encuestas_satisfaccion",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cita_id", sa.Integer(), nullable=False),
            sa.Column("cliente_id", sa.Integer(), nullable=False),
            sa.Column("calificacion", sa.Integer(), nullable=False),
            sa.Column("comentario", sa.Text(), nullable=True),
            sa.Column("fecha_envio", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("respondido", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.CheckConstraint("calificacion >= 1 AND calificacion <= 5", name="ck_encuestas_calificacion_1_5"),
            sa.ForeignKeyConstraint(["cita_id"], ["citas.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["cliente_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cita_id", "cliente_id", name="uq_encuestas_cita_cliente"),
        )

    if not inspector.has_table("fotos_mascota"):
        op.create_table(
            "fotos_mascota",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mascota_id", sa.Integer(), nullable=False),
            sa.Column("url_foto", sa.Text(), nullable=False),
            sa.Column("nombre_archivo", sa.String(length=255), nullable=True),
            sa.Column("fecha_subida", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["mascota_id"], ["mascotas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("documentos_mascota"):
        op.create_table(
            "documentos_mascota",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mascota_id", sa.Integer(), nullable=False),
            sa.Column("archivo", sa.Text(), nullable=False),
            sa.Column("nombre_archivo", sa.String(length=255), nullable=True),
            sa.Column("tipo_documento", sa.String(length=100), nullable=True),
            sa.Column("fecha_subida", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["mascota_id"], ["mascotas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    op.drop_table("documentos_mascota")
    op.drop_table("fotos_mascota")
    op.drop_table("encuestas_satisfaccion")
    op.drop_table("chatbot_faq")
