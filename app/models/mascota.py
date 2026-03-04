from app.extensions import db


# --- MODELOS DE DATOS ---
class Mascota(db.Model):
    # Representa a una mascota registrada junto con su dueño y datos clínicos.
    __tablename__ = "mascotas"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    fecha_nacimiento = db.Column(db.Date, nullable=False)
    peso = db.Column(db.Float, nullable=True)
    raza = db.Column(db.String(100), nullable=True)
    especie = db.Column(db.Enum("perro", "gato", "otro", name="especie_mascota"), nullable=False)
    sexo = db.Column(db.Enum("macho", "hembra", name="sexo_mascota"), nullable=False)
    datos_adicionales = db.Column(db.Text, nullable=True)
    estado = db.Column(db.Enum("activa", "inactiva", name="estado_mascota"), nullable=False, default="activa")
    razon_inactivacion = db.Column(db.Text, nullable=True)
    dueno_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    comportamiento = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )
