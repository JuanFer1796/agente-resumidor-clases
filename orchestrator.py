"""
orchestrator.py
===============
Orquesta el flujo diario, paso por paso, con logging y manejo de fallos:

    1. Cargar corpus            (frases_processor)
    2. Seleccionar frase        (frases_processor)
    3. Personalizar con Gemini  (gemini_personalizador)
    4. Enviar por Telegram      (telegram_sender)
    5. Registrar historial y estadísticas

Cada paso es un método independiente y testeable. Si un paso no crítico falla
(Gemini), el flujo continúa en modo respaldo; si falla uno crítico (corpus,
Telegram), la corrida termina con error.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import config
from frases_processor import CorpusError, FrasesProcessor
from gemini_personalizador import GeminiPersonalizador, mensaje_respaldo
from telegram_sender import TelegramSender

logger = logging.getLogger(__name__)


@dataclass
class Resultado:
    """Resumen de la corrida, usado para el log final y el exit code."""

    exito: bool = False
    frase_id: str | None = None
    uso_gemini: bool = False
    dry_run: bool = False
    error: str | None = None
    duracion_s: float = 0.0
    estadisticas: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    """Coordina los cuatro componentes del agente."""

    def __init__(
        self,
        credenciales: config.Credenciales,
        usar_gemini: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.credenciales = credenciales
        self.usar_gemini = usar_gemini
        self.dry_run = dry_run
        self.procesador = FrasesProcessor()
        self.telegram = TelegramSender(
            bot_token=credenciales.telegram_bot_token,
            chat_id=credenciales.telegram_chat_id,
        )

    # ------------------------------------------------------------- ejecución
    def ejecutar(self, frase_id: str | None = None) -> Resultado:
        """Corre el flujo completo. No lanza excepciones: las devuelve en Resultado."""
        inicio = time.monotonic()
        resultado = Resultado(dry_run=self.dry_run)

        try:
            # --- Paso 1: corpus -------------------------------------------
            logger.info("── Paso 1/4: leyendo el corpus ──")
            self.procesador.cargar_corpus()

            # --- Paso 2: selección ----------------------------------------
            logger.info("── Paso 2/4: seleccionando la frase del día ──")
            frase = (
                self.procesador.obtener_por_id(frase_id)
                if frase_id
                else self.procesador.seleccionar_aleatoria()
            )
            resultado.frase_id = frase["id"]
            logger.info("Texto original: «%s»", frase["text"])

            # --- Paso 3: personalización ----------------------------------
            logger.info("── Paso 3/4: personalizando con Gemini ──")
            texto, uso_gemini = self._personalizar(frase)
            resultado.uso_gemini = uso_gemini
            logger.info("Mensaje final:\n%s", texto)

            # --- Paso 4: envío --------------------------------------------
            logger.info("── Paso 4/4: enviando por Telegram ──")
            if self.dry_run:
                vista = TelegramSender.formatear_recordatorio(texto, frase, uso_gemini)
                logger.info("DRY-RUN activo. No se envía nada. Vista previa:\n%s", vista)
                resultado.exito = True
            else:
                enviado = self.telegram.enviar_recordatorio(texto, frase, uso_gemini)
                if not enviado:
                    raise RuntimeError(
                        "Telegram no aceptó el mensaje (ver errores anteriores)."
                    )
                self.procesador.registrar_envio(frase)
                resultado.exito = True

        except CorpusError as exc:
            resultado.error = f"Corpus: {exc}"
            logger.exception("Fallo crítico leyendo el corpus.")
        except Exception as exc:  # noqa: BLE001
            resultado.error = str(exc)
            logger.exception("Fallo durante la ejecución del agente.")

        resultado.duracion_s = round(time.monotonic() - inicio, 2)
        try:
            resultado.estadisticas = self.procesador.estadisticas()
        except Exception:  # noqa: BLE001
            resultado.estadisticas = {}

        self._log_resumen(resultado)
        return resultado

    # --------------------------------------------------------------- pasos
    def _personalizar(self, frase: dict[str, Any]) -> tuple[str, bool]:
        if not self.usar_gemini or not self.credenciales.gemini_api_key:
            logger.warning("Gemini desactivado; se usa el mensaje de respaldo.")
            return mensaje_respaldo(frase), False

        personalizador = GeminiPersonalizador(api_key=self.credenciales.gemini_api_key)
        return personalizador.personalizar(frase)

    def notificar_error(self, mensaje: str) -> None:
        """Intenta avisar por Telegram que la corrida falló. Nunca lanza."""
        if self.dry_run:
            logger.info("DRY-RUN: se omitió la alerta de error por Telegram.")
            return
        try:
            self.telegram.enviar_alerta_error(mensaje)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tampoco se pudo enviar la alerta de error: %s", exc)

    # --------------------------------------------------------------- salida
    @staticmethod
    def _log_resumen(r: Resultado) -> None:
        logger.info("═════════════ RESUMEN ═════════════")
        logger.info("Estado           : %s", "ÉXITO" if r.exito else "ERROR")
        logger.info("Frase            : %s", r.frase_id or "—")
        logger.info("Personalización  : %s", "Gemini" if r.uso_gemini else "respaldo local")
        logger.info("Modo             : %s", "dry-run" if r.dry_run else "envío real")
        logger.info("Duración         : %ss", r.duracion_s)
        if r.estadisticas:
            logger.info("Frases en corpus : %s", r.estadisticas.get("frases_en_corpus"))
            logger.info("Envíos totales   : %s", r.estadisticas.get("recordatorios_enviados"))
        if r.error:
            logger.info("Error            : %s", r.error)
        logger.info("═══════════════════════════════════")
