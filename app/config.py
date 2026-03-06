import os
from dotenv import load_dotenv

load_dotenv()


def build_database_uri() -> str:
    # 1) Railway / producción: URL completa
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if database_url.startswith("mysql+mysqlclient://"):
            return database_url.replace("mysql+mysqlclient://", "mysql+mysqldb://", 1)
        if database_url.startswith("mysql://"):
            return database_url.replace("mysql://", "mysql+mysqldb://", 1)
        return database_url

    # 2) Fallback local con variables DB_*
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS")
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_name = os.getenv("DB_NAME")
    if all([db_user, db_pass, db_name]):
        return f"mysql+mysqldb://{db_user}:{db_pass}@{db_host}/{db_name}"

    # 3) Fallback para variables MYSQL* de Railway
    mysql_host = os.getenv("MYSQLHOST")
    mysql_port = os.getenv("MYSQLPORT", "3306")
    mysql_user = os.getenv("MYSQLUSER")
    mysql_password = os.getenv("MYSQLPASSWORD")
    mysql_database = os.getenv("MYSQLDATABASE")
    if all([mysql_host, mysql_user, mysql_password, mysql_database]):
        return (
            f"mysql+mysqldb://{mysql_user}:{mysql_password}"
            f"@{mysql_host}:{mysql_port}/{mysql_database}"
        )

    raise RuntimeError(
        "No se encontró configuración de base de datos. "
        "Define DATABASE_URL o las variables DB_* / MYSQL*."
    )

class Config:
    SQLALCHEMY_DATABASE_URI = build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    API_BASE_URL = "http://127.0.0.1:5000"
