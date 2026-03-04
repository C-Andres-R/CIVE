import re
import unicodedata


# --- VALIDACIONES DE CONTRASENAS ---
COMMON_PASSWORDS = {
    "123456",
    "123456789",
    "password",
    "qwerty",
    "abc123",
    "admin",
    "letmein",
}


def validate_password(password: str, *, correo: str = "", nombre: str = "") -> list[str]:
    # Valida que una contraseña cumpla las reglas de seguridad del sistema.
    errors: list[str] = []
    pwd = (password or "").strip()
    pwd_norm = _normalize(pwd)

    if len(pwd) < 12:
        errors.append("La contraseña debe tener al menos 12 caracteres.")
    if not re.search(r"[A-Z]", pwd):
        errors.append("La contraseña debe incluir al menos una letra mayúscula.")
    if not re.search(r"[a-z]", pwd):
        errors.append("La contraseña debe incluir al menos una letra minúscula.")
    if not re.search(r"\d", pwd):
        errors.append("La contraseña debe incluir al menos un número.")
    if not re.search(r"[^A-Za-z0-9]", pwd):
        errors.append("La contraseña debe incluir al menos un carácter especial.")

    if pwd.lower() in COMMON_PASSWORDS:
        errors.append("La contraseña es demasiado común.")

    correo_l = _normalize((correo or "").strip())
    nombre_l = _normalize((nombre or "").strip())

    if correo_l:
        local_part = correo_l.split("@")[0]
        if local_part and local_part in pwd_norm:
            errors.append("La contraseña no debe contener parte del correo.")
    if nombre_l:
        # Revisamos si la contraseña incluye partes reconocibles del nombre.
        name_tokens = re.findall(r"[a-z0-9]+", nombre_l)
        if any(len(token) >= 3 and token in pwd_norm for token in name_tokens):
            errors.append("La contraseña no debe contener el nombre del usuario.")

    return errors


def _normalize(value: str) -> str:
    # Normaliza un texto para compararlo sin acentos ni diferencias de mayúsculas.
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.lower()
