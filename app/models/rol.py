from app.extensions import db

# --- MODELOS DE DATOS ---
class Rol(db.Model):
    # Representa un tipo de rol disponible dentro del sistema.
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique = True)

    usuarios = db.relationship("Usuario", back_populates="rol")
