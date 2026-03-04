from app.extensions import db

# --- MODELOS DE DATOS ---
class Permiso(db.Model):
    # Representa un permiso que puede asignarse a los roles.
    __tablename__ = 'permisos'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
