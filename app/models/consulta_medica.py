"""Módulo de consulta medica."""

from app.extensions import db


class ConsultaMedica(db.Model):
    """Clase para consulta medica."""
    __tablename__ = "consultas_medicas"

    id = db.Column(db.Integer, primary_key=True)
    mascota_id = db.Column(db.Integer, db.ForeignKey("mascotas.id", ondelete="CASCADE"), nullable=False)
    veterinario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    insumo_clinico_id = db.Column(db.Integer, db.ForeignKey("insumos_clinicos.id"), nullable=True)
    vacuna_insumo_id = db.Column(db.Integer, db.ForeignKey("insumos_clinicos.id"), nullable=True)
    tipo_analisis_relacionado = db.Column(db.String(120), nullable=True)
    fecha_consulta = db.Column(db.Date, nullable=False)
    sintomas = db.Column(db.Text, nullable=False)
    diagnostico = db.Column(db.Text, nullable=False)
    tratamiento = db.Column(db.Text, nullable=False)
    medicamentos_administrados = db.Column(db.Text, nullable=True)
    fecha_administracion = db.Column(db.Date, nullable=True)
    dosis = db.Column(db.String(120), nullable=True)
    periodo_administracion = db.Column(db.String(120), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    precio_consulta = db.Column(db.Numeric(10, 2), nullable=False, default=300)
    fecha_creacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
