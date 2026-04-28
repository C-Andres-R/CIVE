"""Módulo de encuesta satisfaccion."""

from app.extensions import db


class EncuestaSatisfaccion(db.Model):
    """Clase para encuesta satisfaccion."""
    # Guarda la encuesta de satisfacción asociada a una cita.
    __tablename__ = "encuestas_satisfaccion"

    id = db.Column(db.Integer, primary_key=True)
    cita_id = db.Column(db.Integer, db.ForeignKey("citas.id"), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    calificacion = db.Column(db.Integer, nullable=True)
    conforme = db.Column(db.Boolean, nullable=True)
    detalle_inconformidad = db.Column(db.String(300), nullable=True)
    comentario = db.Column(db.Text, nullable=True)
    fecha_programada_envio = db.Column(db.DateTime, nullable=True)
    fecha_envio = db.Column(db.DateTime, nullable=True)
    fecha_respuesta = db.Column(db.DateTime, nullable=True)
    correo_enviado = db.Column(db.Boolean, nullable=False, default=False)
    respondido = db.Column(db.Boolean, nullable=False, default=False)
