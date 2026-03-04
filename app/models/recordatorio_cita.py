from app.extensions import db


# --- MODELOS DE DATOS ---
class RecordatorioCita(db.Model):
    # Representa el estado de envío y confirmación de un recordatorio de cita.
    __tablename__ = "recordatorios_citas"

    id = db.Column(db.Integer, primary_key=True)
    cita_id = db.Column(db.Integer, db.ForeignKey("citas.id"), nullable=False, unique=True)
    estado = db.Column(
        db.Enum("programado", "enviado", name="estado_recordatorio_cita"),
        nullable=False,
        default="programado",
    )
    enviado_en = db.Column(db.DateTime, nullable=True)
    confirmado = db.Column(db.Boolean, nullable=False, default=False)
    confirmado_en = db.Column(db.DateTime, nullable=True)
    token_confirmacion = db.Column(db.String(128), nullable=True, unique=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
