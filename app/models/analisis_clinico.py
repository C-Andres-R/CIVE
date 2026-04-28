"""Módulo de analisis clinico."""

from app.extensions import db


class AnalisisClinico(db.Model):
    """Clase para analisis clinico."""
    __tablename__ = "analisis_clinicos"

    id = db.Column(db.Integer, primary_key=True)
    mascota_id = db.Column(db.Integer, db.ForeignKey("mascotas.id", ondelete="CASCADE"), nullable=False)
    veterinario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    fecha_analisis = db.Column(db.Date, nullable=False)
    tipo_analisis = db.Column(db.String(120), nullable=False)
    resultados = db.Column(db.Text, nullable=False)
    precio = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    documentos_adjuntos = db.Column(db.Text, nullable=True)
    archivo_adjunto = db.Column(db.Text, nullable=True)
    nombre_archivo = db.Column(db.String(255), nullable=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
