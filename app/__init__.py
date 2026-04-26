import os
from flask import Flask
from dotenv import load_dotenv
from app.config import Config
from app.extensions import db, migrate, jwt
from app.followups import asegurar_tabla_seguimientos

def create_app():
    # Crea la aplicación Flask y registra sus extensiones y rutas.
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    from app import models
    with app.app_context():
        asegurar_tabla_seguimientos()

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

    from app.routes.encuestas import encuestas_bp, sincronizar_encuestas_programadas
    app.register_blueprint(encuestas_bp)

    from app.routes.citas import citas_bp, sincronizar_recordatorios_programados
    app.register_blueprint(citas_bp)

    from app.routes.mascotas import mascotas_bp
    app.register_blueprint(mascotas_bp)

    from app.routes.clientes import clientes_bp
    app.register_blueprint(clientes_bp)

    from app.routes.expedientes import expedientes_bp
    app.register_blueprint(expedientes_bp)

    from app.routes.reportes import reportes_bp
    app.register_blueprint(reportes_bp)

    from app.routes.datos import datos_bp
    app.register_blueprint(datos_bp)

    @app.before_request
    def _sincronizar_tareas_automaticas():
        from flask import request
        from app.followups import sincronizar_seguimientos_programados

        if not request.endpoint or request.endpoint == "static":
            return None
        try:
            sincronizar_recordatorios_programados()
            sincronizar_encuestas_programadas()
            sincronizar_seguimientos_programados()
        except Exception:
            db.session.rollback()
        return None

    return app
