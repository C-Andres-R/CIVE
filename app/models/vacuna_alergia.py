from app.extensions import db


class VacunaAlergia(db.Model):
    __tablename__ = "vacunas_alergias"

    id = db.Column(db.Integer, primary_key=True)
    mascota_id = db.Column(db.Integer, db.ForeignKey("mascotas.id", ondelete="CASCADE"), nullable=False)
    veterinario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    insumo_clinico_id = db.Column(db.Integer, db.ForeignKey("insumos_clinicos.id"), nullable=True)
    tipo_registro = db.Column(
        db.Enum("vacuna", "alergia", name="tipo_registro_clinico"),
        nullable=False,
    )
    fecha_registro = db.Column(db.Date, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    reaccion_identificada = db.Column(db.Text, nullable=True)
    notas_adicionales = db.Column(db.Text, nullable=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
