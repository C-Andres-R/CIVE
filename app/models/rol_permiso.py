from app.extensions import db

# --- MODELOS DE DATOS ---
class RolPermiso(db.Model):
    # Relaciona cada rol con los permisos que tiene asignados.
    __tablename__ = 'roles_permisos'

    rol_id = db.Column(
        db.Integer,
        db.ForeignKey('roles.id'),
        primary_key=True
    )
    permiso_id = db.Column(
        db.Integer,
        db.ForeignKey('permisos.id'),
        primary_key=True
    )

