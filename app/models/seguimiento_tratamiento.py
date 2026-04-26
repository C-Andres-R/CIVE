from app.extensions import db


class SeguimientoTratamiento(db.Model):
    # Representa un seguimiento automático pendiente para el veterinario.
    __tablename__ = "seguimientos_tratamientos"

    id = db.Column(db.Integer, primary_key=True)
    origen_tipo = db.Column(
        db.Enum("cita", "consulta", "vacuna_alergia", "analisis_clinico", name="origen_seguimiento_tratamiento"),
        nullable=False,
    )
    origen_id = db.Column(db.Integer, nullable=False)
    evento_tipo = db.Column(
        db.Enum("cita", "medicamento", "vacuna", "analisis", name="evento_seguimiento_tratamiento"),
        nullable=False,
    )
    mascota_id = db.Column(db.Integer, db.ForeignKey("mascotas.id", ondelete="CASCADE"), nullable=False)
    veterinario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    programado_para = db.Column(db.DateTime, nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    estado = db.Column(
        db.Enum("programado", "enviado", name="estado_seguimiento_tratamiento"),
        nullable=False,
        default="programado",
    )
    enviado_en = db.Column(db.DateTime, nullable=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint("origen_tipo", "origen_id", "evento_tipo", name="uq_seguimiento_origen_evento"),
    )
