"""hu003 recordatorios citas

Revision ID: 496ea11f6db8
Revises: fde14f0dacda
Create Date: 2026-02-22 23:40:54.030337

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '496ea11f6db8'
down_revision = 'fde14f0dacda'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recordatorios_citas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cita_id', sa.Integer(), nullable=False),
    sa.Column('estado', sa.Enum('programado', 'enviado', name='estado_recordatorio_cita'), nullable=False),
    sa.Column('enviado_en', sa.DateTime(), nullable=True),
    sa.Column('confirmado', sa.Boolean(), nullable=False),
    sa.Column('confirmado_en', sa.DateTime(), nullable=True),
    sa.Column('token_confirmacion', sa.String(length=128), nullable=True),
    sa.Column('fecha_creacion', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['cita_id'], ['citas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cita_id'),
    sa.UniqueConstraint('token_confirmacion')
    )


def downgrade():
    op.drop_table('recordatorios_citas')
