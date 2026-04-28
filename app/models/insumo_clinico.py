"""Módulo de insumo clinico."""

from app.extensions import db


class InsumoClinico(db.Model):
    """Clase para insumo clinico."""
    __tablename__ = "insumos_clinicos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    tipo_insumo = db.Column(
        db.Enum("medicamento", "vacuna", name="tipo_insumo_clinico"),
        nullable=False,
    )
    fecha_caducidad = db.Column(db.Date, nullable=False)
    cantidad_existencia = db.Column(db.Integer, nullable=False, default=0)
    precio = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
