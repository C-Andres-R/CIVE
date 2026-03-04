from app.extensions import db


class EncuestaSatisfaccion(db.Model):
    # Guarda la evaluacion posterior a una cita.
    __tablename__ = "encuestas_satisfaccion"

    id = db.Column(db.Integer, primary_key=True)
    cita_id = db.Column(db.Integer, db.ForeignKey("citas.id"), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    calificacion = db.Column(db.Integer, nullable=False)
    comentario = db.Column(db.Text, nullable=True)
    fecha_envio = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    respondido = db.Column(db.Boolean, nullable=False, default=True)

