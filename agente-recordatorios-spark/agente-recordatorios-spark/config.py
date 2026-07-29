"""
config.py
=========
Configuración central del agente de recordatorios Spark.

Responsabilidades:
  - Cargar variables de entorno (.env local o GitHub Secrets en Actions).
  - Validar que las 3 credenciales existan y tengan formato razonable.
  - Exponer el PERFIL del usuario (lo que Gemini usa para personalizar).
  - Configurar el logging centralizado (consola + archivo rotativo diario).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Rutas del proyecto
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CORPUS_PATH = BASE_DIR / "corpus_frases.json"
HISTORIAL_PATH = BASE_DIR / "historial.json"
LOGS_DIR = BASE_DIR / "logs"

# Carga el .env local si existe. En GitHub Actions no existe y las variables
# llegan directamente del entorno (secrets), así que esto es inofensivo.
load_dotenv(BASE_DIR / ".env")

# --------------------------------------------------------------------------
# Parámetros configurables por entorno
# --------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TIMEZONE = os.getenv("TIMEZONE", "America/Guatemala")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_REINTENTOS = int(os.getenv("GEMINI_MAX_REINTENTOS", "3"))
TELEGRAM_MAX_REINTENTOS = int(os.getenv("TELEGRAM_MAX_REINTENTOS", "3"))
TELEGRAM_TIMEOUT = int(os.getenv("TELEGRAM_TIMEOUT", "20"))
# Cuántas frases recientes se recuerdan para no repetirlas.
HISTORIAL_MAX = int(os.getenv("HISTORIAL_MAX", "25"))

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Se lanza cuando falta una credencial o su formato es inválido."""


# --------------------------------------------------------------------------
# Perfil del usuario  → editá esto y cambia toda la personalización
# --------------------------------------------------------------------------
PERFIL: dict[str, object] = {
    "nombre": "Juan Fernando Ramírez",
    "nombre_corto": "Juan",
    "edad": 29,
    "profesion": "Trabaja en un banco",
    "ciudad": "Guatemala",
    "lectura_actual": "Beating Wall Street",
    "hobbies": ["correr", "programar"],
    "animes": [
        "Mob Psycho 100",
        "Naruto",
        "One Piece",
        "Berserk",
        "Fullmetal Alchemist",
        "One Punch Man",
        "Kimetsu no Yaiba",
        "Jujutsu Kaisen",
        "Frieren",
        "Cyberpunk: Edgerunners",
        "películas de Studio Ghibli",
    ],
    "deporte": "fútbol",
    "equipo": "Arsenal",
}


def perfil_como_texto() -> str:
    """Devuelve el perfil en un bloque de texto listo para inyectar en el prompt."""
    return (
        f"- Nombre: {PERFIL['nombre']} (llamarlo «{PERFIL['nombre_corto']}»)\n"
        f"- Edad: {PERFIL['edad']} años\n"
        f"- Trabajo: {PERFIL['profesion']}, en {PERFIL['ciudad']}\n"
        f"- Libro que está leyendo: «{PERFIL['lectura_actual']}»\n"
        f"- Hobbies: {', '.join(PERFIL['hobbies'])}\n"
        f"- Animes/películas favoritas: {', '.join(PERFIL['animes'])}\n"
        f"- Deporte: {PERFIL['deporte']}; hincha del {PERFIL['equipo']}"
    )


# --------------------------------------------------------------------------
# Credenciales
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Credenciales:
    """Contenedor inmutable de los 3 secrets."""

    gemini_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str

    def enmascarado(self) -> str:
        """Representación segura para logs (nunca imprime el valor completo)."""

        def mask(valor: str) -> str:
            return f"{valor[:4]}…{valor[-4:]}" if len(valor) > 8 else "…"

        return (
            f"GEMINI_API_KEY={mask(self.gemini_api_key)} "
            f"TELEGRAM_BOT_TOKEN={mask(self.telegram_bot_token)} "
            f"TELEGRAM_CHAT_ID={mask(self.telegram_chat_id)}"
        )


def _leer_var(nombre: str) -> str:
    valor = (os.getenv(nombre) or "").strip()
    if not valor:
        raise ConfigError(
            f"Falta la variable de entorno «{nombre}». "
            f"Definila en tu .env local o como GitHub Secret."
        )
    return valor


def cargar_credenciales(requiere_gemini: bool = True) -> Credenciales:
    """
    Lee y valida las credenciales.

    Args:
        requiere_gemini: si es False, permite correr sin GEMINI_API_KEY
                         (modo --sin-gemini, útil para probar solo Telegram).

    Raises:
        ConfigError: si falta algo obligatorio.
    """
    faltantes: list[str] = []

    try:
        token = _leer_var("TELEGRAM_BOT_TOKEN")
    except ConfigError as exc:
        faltantes.append(str(exc))
        token = ""

    try:
        chat_id = _leer_var("TELEGRAM_CHAT_ID")
    except ConfigError as exc:
        faltantes.append(str(exc))
        chat_id = ""

    gemini_key = ""
    if requiere_gemini:
        try:
            gemini_key = _leer_var("GEMINI_API_KEY")
        except ConfigError as exc:
            faltantes.append(str(exc))
    else:
        gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()

    if faltantes:
        raise ConfigError("Configuración incompleta:\n  - " + "\n  - ".join(faltantes))

    # Validaciones de formato: avisan pero no detienen la ejecución,
    # porque los formatos de los proveedores pueden cambiar.
    if ":" not in token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN no contiene ':'. El formato esperado es "
            "123456789:ABCdef... ¿Lo copiaste completo desde @BotFather?"
        )
    if not re.fullmatch(r"-?\d+", chat_id):
        logger.warning(
            "TELEGRAM_CHAT_ID='%s' no parece numérico. Debe ser un número "
            "(los grupos empiezan con '-').",
            chat_id,
        )
    if requiere_gemini and not gemini_key.startswith("AIza"):
        logger.warning(
            "GEMINI_API_KEY no empieza con 'AIza'. Verificá que sea una key de "
            "Google AI Studio (https://aistudio.google.com/app/apikey)."
        )

    return Credenciales(
        gemini_api_key=gemini_key,
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
    )


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
_LOGGING_CONFIGURADO = False


def configurar_logging(nivel: str | None = None) -> logging.Logger:
    """
    Configura el logging del proyecto: consola (stdout) + archivo rotativo diario.

    En GitHub Actions la salida de consola es lo que se ve en los logs del job;
    el archivo `logs/agente.log` sirve para ejecuciones locales.
    """
    global _LOGGING_CONFIGURADO

    root = logging.getLogger()
    if _LOGGING_CONFIGURADO:
        return root

    nivel_final = (nivel or LOG_LEVEL).upper()
    root.setLevel(getattr(logging, nivel_final, logging.INFO))

    formato = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    consola = logging.StreamHandler(stream=sys.stdout)
    consola.setFormatter(formato)
    root.addHandler(consola)

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        archivo = TimedRotatingFileHandler(
            LOGS_DIR / "agente.log",
            when="midnight",
            backupCount=14,
            encoding="utf-8",
        )
        archivo.setFormatter(formato)
        root.addHandler(archivo)
    except OSError as exc:  # sistema de archivos de solo lectura, etc.
        root.warning("No se pudo crear el log en archivo: %s", exc)

    # Silenciar ruido de librerías de terceros.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)

    _LOGGING_CONFIGURADO = True
    return root
