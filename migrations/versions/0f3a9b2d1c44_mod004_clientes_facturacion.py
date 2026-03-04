"""mod004 clientes facturacion

Revision ID: 0f3a9b2d1c44
Revises: 496ea11f6db8
Create Date: 2026-02-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0f3a9b2d1c44"
down_revision = "496ea11f6db8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.add_column(sa.Column("domicilio", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("razon_inactivacion", sa.Text(), nullable=True))

    op.create_table(
        "facturacion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("fecha_pago", sa.DateTime(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("monto_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("descuento", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("monto_pagado", sa.Numeric(10, 2), nullable=False),
        sa.Column("adeudo", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("estado", sa.Enum("pagado", "pendiente", "parcial", name="estado_facturacion"), nullable=False),
        sa.Column("metodo_pago", sa.String(length=50), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["cliente_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("facturacion")

    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.drop_column("razon_inactivacion")
        batch_op.drop_column("domicilio")
