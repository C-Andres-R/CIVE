import os
from flask import Flask
from dotenv import load_dotenv
from app.config import Config
from app.extensions import db, migrate, jwt

# --- CONFIGURACION DE LA APLICACION ---
def create_app():
    # Crea la aplicación Flask y registra sus extensiones y rutas.
    load_dotenv()

    # Cargamos la configuración base de la aplicación.
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # Inicializamos las extensiones principales de Flask.
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    from app import models

    # Registramos los módulos de rutas que usará la aplicación.
    from app.routes.health import health_bp
    app.register_blueprint(health_bp)

    from app.routes.pages import pages_bp
    app.register_blueprint(pages_bp)

    from app.auth.routes import auth_bp
    app.register_blueprint(auth_bp)

    from app.routes.usuarios import usuarios_bp
    app.register_blueprint(usuarios_bp)

    from app.routes.chat import chat_bp
    app.register_blueprint(chat_bp)

    from app.routes.citas import citas_bp
    app.register_blueprint(citas_bp)

    from app.routes.mascotas import mascotas_bp
    app.register_blueprint(mascotas_bp)

    from app.routes.clientes import clientes_bp
    app.register_blueprint(clientes_bp)

    return app
