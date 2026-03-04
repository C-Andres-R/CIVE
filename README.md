# CIVE

Sistema web de gestión administrativa para CIVE.

## Requisitos

- Python 3.12+ (recomendado 3.13)
- MySQL
- `pip`

## Instalación

```bash
cd /Users/andresramirez/Documents/cive
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuración

1. Copia el archivo de ejemplo:

```bash
cp .env.example .env
```

2. Ajusta credenciales de base de datos, JWT y SMTP en `.env`.

Variables clave:

- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_NAME`
- `API_BASE_URL` (por defecto `http://127.0.0.1:5000`)

## Migraciones

Aplica el esquema vigente con Alembic:

```bash
source venv/bin/activate
flask --app run.py db upgrade
```

## Seed demo (opcional)

Carga datos mínimos de demo (`admin`, `veterinario`, `cliente`, mascota, cita y facturación):

```bash
mysql -u "$DB_USER" -p"$DB_PASSWORD" -h "$DB_HOST" "$DB_NAME" < seeds/seed_demo.sql
```

Credenciales demo están documentadas dentro de:

- `seeds/seed_demo.sql`

## Ejecución local

```bash
source venv/bin/activate
python run.py
```

La app queda en:

- `http://127.0.0.1:5000`

## Despliegue en Railway

El proyecto ya incluye:

- `gunicorn` en `requirements.txt`
- `Procfile` con:
  - `web: gunicorn wsgi:app --bind 0.0.0.0:$PORT`

Variables mínimas que debes configurar en Railway:

- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_NAME`
- `API_BASE_URL` (URL pública de tu app en Railway)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS` (si usarás notificaciones)
- `ADMIN_EMAIL`
- `CLINIC_PHONE`

## Estructura relevante

- `app/` aplicación Flask (rutas, modelos, templates, estáticos)
- `migrations/` historial de migraciones
- `schema.sql` esquema de referencia
- `seeds/seed_demo.sql` dataset demo reproducible
