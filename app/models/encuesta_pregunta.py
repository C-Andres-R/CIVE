"""Módulo de encuesta pregunta."""

from app.extensions import db


class EncuestaPregunta(db.Model):
    """Clase para encuesta pregunta."""
    # Permite configurar el texto visible de las preguntas base de la encuesta.
    __tablename__ = "encuestas_preguntas"

    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(80), nullable=False, unique=True)
    texto = db.Column(db.String(255), nullable=False)
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
