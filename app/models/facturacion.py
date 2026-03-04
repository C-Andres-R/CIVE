from app.extensions import db


# --- MODELOS DE DATOS ---
class Facturacion(db.Model):
    # Representa un registro de facturración asociado a un cliente.
    __tablename__ = "facturacion"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    fecha_pago = db.Column(db.DateTime, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    monto_total = db.Column(db.Numeric(10, 2), nullable=False)
    descuento = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    monto_pagado = db.Column(db.Numeric(10, 2), nullable=False)
    adeudo = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    estado = db.Column(
        db.Enum("pagado", "pendiente", "parcial", name="estado_facturacion"),
        nullable=False,
        default="pendiente",
    )
    metodo_pago = db.Column(db.String(50), nullable=False)
    observaciones = db.Column(db.Text, nullable=True)
