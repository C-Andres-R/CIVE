from app.extensions import db


# --- MODELOS DE DATOS ---
class Cita(db.Model):
    # Representa una cita médica entre un cliente, su mascota y un veterinario.
    __tablename__ = "citas"

    id = db.Column(db.Integer, primary_key=True)
    fecha_hora = db.Column(db.DateTime, nullable=False)
    motivo = db.Column(db.Text, nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    veterinario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    mascota_id = db.Column(db.Integer, db.ForeignKey("mascotas.id"), nullable=False)
    estado = db.Column(
        db.Enum("pendiente", "confirmada", "cancelada", name="estado_cita"),
        nullable=False,
        default="pendiente",
    )
    cancelada = db.Column(db.Boolean, nullable=False, default=False)
    fecha_creacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
