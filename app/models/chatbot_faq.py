from app.extensions import db


class ChatbotFaq(db.Model):
    # Almacena preguntas frecuentes administrables para el chat.
    __tablename__ = "chatbot_faq"

    id = db.Column(db.Integer, primary_key=True)
    pregunta = db.Column(db.String(255), nullable=False, unique=True)
    respuesta = db.Column(db.Text, nullable=False)

