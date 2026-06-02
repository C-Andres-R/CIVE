"""Módulo de init."""

import os
from flask import Flask, flash, jsonify, redirect, request, session, url_for
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from app.config import Config
from app.extensions import db, migrate, jwt
from app.followups import asegurar_tabla_seguimientos
from app.security import (
    clear_authenticated_session,
    generate_csrf_token,
    is_session_expired,
    mark_session_authenticated,
    should_validate_csrf,
    validate_csrf_request,
)


CSRF_EXEMPT_ENDPOINTS = {"auth.login"}
RUN_INLINE_SYNC_TASKS = os.getenv("RUN_INLINE_SYNC_TASKS", "false").strip().lower() == "true"

def create_app():
    """Función para create app."""
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
        try:
            asegurar_tabla_seguimientos()
        except SQLAlchemyError:
            db.session.rollback()

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

    @app.context_processor
    def _inject_security_helpers():
        """Función para inject security helpers."""
        return {"csrf_token": generate_csrf_token}

    @app.before_request
    def _proteger_sesion_y_sincronizar_tareas():
        """Función para proteger sesion y sincronizar tareas."""
        from app.followups import sincronizar_seguimientos_programados

        if not request.endpoint or request.endpoint == "static":
            return None

        if session.get("access_token"):
            if is_session_expired(app.config["SESSION_IDLE_TIMEOUT_SECONDS"]):
                clear_authenticated_session()
                if request.is_json:
                    return jsonify({"ok": False, "message": "Tu sesión expiró. Inicia sesión de nuevo."}), 401
                flash("Tu sesión expiró por inactividad. Inicia sesión de nuevo.", "error")
                return redirect(url_for("pages.pagina_inicio_sesion"))
            mark_session_authenticated()

        if should_validate_csrf() and request.endpoint not in CSRF_EXEMPT_ENDPOINTS:
            if not validate_csrf_request():
                if request.is_json:
                    return jsonify({
                        "ok": False,
                        "message": "La solicitud no pasó la validación de seguridad. Recarga la página e inténtalo de nuevo.",
                    }), 400
                flash("La solicitud no pasó la validación de seguridad. Recarga la página e inténtalo de nuevo.", "error")
                return redirect(request.referrer or url_for("pages.pagina_inicio_sesion"))

        if RUN_INLINE_SYNC_TASKS:
            try:
                sincronizar_recordatorios_programados()
                sincronizar_encuestas_programadas()
                sincronizar_seguimientos_programados()
            except Exception:
                db.session.rollback()
        return None

    @app.after_request
    def _aplicar_headers_seguridad(response):
        """Función para aplicar headers seguridad."""
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.endpoint and request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    return app
