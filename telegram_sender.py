"""
telegram_sender.py
==================
Envío de mensajes a Telegram vía Bot API.

Notas de diseño:
  - Se usa parse_mode=HTML en lugar de Markdown: Markdown revienta con
    guiones, guiones bajos y asteriscos que Gemini puede generar. Con HTML
    basta escapar <, > y & del contenido dinámico.
  - Reintentos con backoff exponencial y respeto de `retry_after` en 429.
"""

from __future__ import annotations

import html
import logging
import random
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

import config

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/{metodo}"
LIMITE_TELEGRAM = 4096  # caracteres por mensaje

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIAS = [
    "lunes", "martes", "miércoles", "jueves",
    "viernes", "sábado", "domingo",
]


class TelegramError(RuntimeError):
    """Error irrecuperable al enviar por Telegram."""


class TelegramSender:
    """Cliente mínimo de la Bot API, limitado a lo que este agente necesita."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: int | None = None,
        max_reintentos: int | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout or config.TELEGRAM_TIMEOUT
        self.max_reintentos = max_reintentos or config.TELEGRAM_MAX_REINTENTOS

    # ------------------------------------------------------------- conexión
    def validar_conexion(self) -> bool:
        """Verifica el token con getMe. No garantiza que el chat_id sea válido."""
        try:
            r = requests.get(
                API_BASE.format(token=self.bot_token, metodo="getMe"),
                timeout=self.timeout,
            )
            data = r.json()
            if r.status_code == 200 and data.get("ok"):
                bot = data["result"]
                logger.info(
                    "Conexión con Telegram OK: @%s (%s).",
                    bot.get("username"),
                    bot.get("first_name"),
                )
                return True
            logger.error(
                "Telegram rechazó el token (HTTP %s): %s",
                r.status_code,
                data.get("description", data),
            )
            return False
        except requests.RequestException as exc:
            logger.error("No se pudo contactar la API de Telegram: %s", exc)
            return False

    # --------------------------------------------------------------- envíos
    def enviar_mensaje(self, texto_html: str, silencioso: bool = False) -> bool:
        """
        Envía un mensaje ya formateado en HTML. Devuelve True si se entregó.

        `texto_html` debe venir con el contenido dinámico ya escapado.
        """
        if len(texto_html) > LIMITE_TELEGRAM:
            logger.warning(
                "Mensaje de %d caracteres excede el límite; se recorta.",
                len(texto_html),
            )
            texto_html = texto_html[: LIMITE_TELEGRAM - 3] + "…"

        payload = {
            "chat_id": self.chat_id,
            "text": texto_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": silencioso,
        }

        for intento in range(1, self.max_reintentos + 1):
            try:
                r = requests.post(
                    API_BASE.format(token=self.bot_token, metodo="sendMessage"),
                    json=payload,
                    timeout=self.timeout,
                )

                if r.status_code == 200:
                    logger.info("Mensaje entregado a chat_id=%s.", self.chat_id)
                    return True

                data = self._json_seguro(r)
                descripcion = data.get("description", r.text[:200])

                # 400 / 403: errores de configuración, no tiene sentido reintentar.
                if r.status_code in (400, 401, 403, 404):
                    logger.error(
                        "Telegram rechazó el envío (HTTP %s): %s",
                        r.status_code,
                        descripcion,
                    )
                    logger.error(self._pista_error(r.status_code, descripcion))
                    return False

                # 429: rate limit, Telegram indica cuántos segundos esperar.
                if r.status_code == 429:
                    espera = data.get("parameters", {}).get("retry_after", 5)
                    logger.warning("Rate limit de Telegram; esperando %ss.", espera)
                    time.sleep(float(espera) + 1)
                    continue

                logger.warning(
                    "Error temporal de Telegram (HTTP %s): %s", r.status_code, descripcion
                )

            except requests.RequestException as exc:
                logger.warning(
                    "Fallo de red al enviar (intento %d/%d): %s",
                    intento,
                    self.max_reintentos,
                    exc,
                )

            if intento < self.max_reintentos:
                espera = (2 ** (intento - 1)) * 2 + random.uniform(0, 1)
                logger.info("Reintentando en %.1fs…", espera)
                time.sleep(espera)

        logger.error("No se pudo entregar el mensaje tras %d intentos.", self.max_reintentos)
        return False

    def enviar_recordatorio(
        self,
        texto_personalizado: str,
        frase: dict[str, Any],
        personalizado_por_gemini: bool = True,
    ) -> bool:
        """Formatea y envía el recordatorio diario."""
        return self.enviar_mensaje(
            self.formatear_recordatorio(
                texto_personalizado, frase, personalizado_por_gemini
            )
        )

    def enviar_alerta_error(self, mensaje: str) -> bool:
        """Notifica un fallo del agente al mismo chat (funcionalidad extra)."""
        cuerpo = (
            "⚠️ <b>Agente Spark: error</b>\n\n"
            f"<pre>{html.escape(mensaje[:1200])}</pre>\n"
            "Revisá los logs en GitHub → Actions."
        )
        return self.enviar_mensaje(cuerpo, silencioso=True)

    # ----------------------------------------------------------- formateo
    @staticmethod
    def formatear_recordatorio(
        texto_personalizado: str,
        frase: dict[str, Any],
        personalizado_por_gemini: bool = True,
    ) -> str:
        """Arma el HTML final del mensaje. Todo el contenido dinámico se escapa."""
        ahora = datetime.now(ZoneInfo(config.TIMEZONE))
        fecha = f"{DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]}"

        partes = [
            f"☀️ <b>Recordatorio Spark</b> · {html.escape(fecha)}",
            "",
            html.escape(texto_personalizado),
            "",
            "──────────",
            f"📖 <i>«{html.escape(frase['text'])}»</i>",
            f"✍️ {html.escape(frase['author'])} — {html.escape(frase['source'])}",
        ]
        if not personalizado_por_gemini:
            partes.append("<i>(modo respaldo: Gemini no respondió hoy)</i>")

        return "\n".join(partes)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _json_seguro(respuesta: requests.Response) -> dict[str, Any]:
        try:
            return respuesta.json()
        except ValueError:
            return {}

    @staticmethod
    def _pista_error(status: int, descripcion: str) -> str:
        desc = descripcion.lower()
        if "chat not found" in desc:
            return (
                "Pista: el TELEGRAM_CHAT_ID es incorrecto, o nunca le escribiste "
                "/start a tu bot. Mandale un mensaje al bot y volvé a intentar."
            )
        if "unauthorized" in desc or status == 401:
            return "Pista: el TELEGRAM_BOT_TOKEN es inválido. Regeneralo con @BotFather."
        if "can't parse entities" in desc:
            return "Pista: HTML mal formado en el mensaje. Revisá el escapado."
        if "bot was blocked" in desc:
            return "Pista: bloqueaste al bot en Telegram. Desbloquealo."
        return "Pista: revisá los 3 secrets en GitHub → Settings → Secrets → Actions."
