from app.extensions import db

# --- MODELOS DE DATOS ---
class Usuario(db.Model):
    # Representa a un usuario del sistema con sus datos de acceso y rol.
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(255), nullable=False)
    nombres = db.Column(db.String(120))
    apellido_paterno = db.Column(db.String(80))
    apellido_materno = db.Column(db.String(80))
    correo = db.Column(db.String(255), nullable=False, unique=True)
    contrasena = db.Column(db.String(255), nullable=False)
    domicilio = db.Column(db.String(255))
    calle = db.Column(db.String(120))
    numero = db.Column(db.String(30))
    colonia = db.Column(db.String(120))
    codigo_postal = db.Column(db.String(10))
    estado = db.Column(db.String(80))
    entidad = db.Column(db.String(80))
    telefono = db.Column(db.String(20))
    razon_inactivacion = db.Column(db.Text)

    activo = db.Column(db.Boolean, nullable=False, default=True)
    eliminado = db.Column(db.Boolean, nullable=False, default=False)

    rol_id = db.Column(
        db.Integer,
        db.ForeignKey("roles.id"),
        nullable=False
    )

    rol = db.relationship("Rol", back_populates="usuarios")
