from app.extensions import db


class DocumentoMascota(db.Model):
    __tablename__ = "documentos_mascota"

    id = db.Column(db.Integer, primary_key=True)
    mascota_id = db.Column(db.Integer, db.ForeignKey("mascotas.id"), nullable=False)
    archivo = db.Column(db.Text, nullable=False)
    nombre_archivo = db.Column(db.String(255), nullable=True)
    tipo_documento = db.Column(db.String(100), nullable=True)
    fecha_subida = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
