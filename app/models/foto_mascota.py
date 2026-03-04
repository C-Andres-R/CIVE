from app.extensions import db


class FotoMascota(db.Model):
    # Registra una foto asociada a una mascota.
    __tablename__ = "fotos_mascota"

    id = db.Column(db.Integer, primary_key=True)
    mascota_id = db.Column(db.Integer, db.ForeignKey("mascotas.id"), nullable=False)
    url_foto = db.Column(db.Text, nullable=False)
    nombre_archivo = db.Column(db.String(255), nullable=True)
    fecha_subida = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

