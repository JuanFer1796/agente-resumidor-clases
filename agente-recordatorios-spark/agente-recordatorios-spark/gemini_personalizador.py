"""
gemini_personalizador.py
========================
Convierte una frase del corpus Spark en un mensaje personalizado para Juan,
usando la API de Gemini (SDK oficial `google-genai`).

Diseño:
  - Reintentos con backoff exponencial ante errores transitorios (429/5xx/red).
  - Fallback local: si Gemini falla definitivamente, se arma un mensaje simple
    para que el recordatorio llegue igual. Nunca se pierde el envío diario.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)


SYSTEM_INSTRUCTION = """\
Sos un escritor breve que redacta recordatorios matutinos en español (variante \
guatemalteca, natural, sin voseo forzado). Tu trabajo es tomar una frase de un \
corpus literario y convertirla en un mensaje corto y personal para una persona \
concreta, que lo leerá a las 6 de la mañana antes de arrancar el día.

REGLAS ESTRICTAS:
1. Longitud: entre 40 y 80 palabras. Nunca más.
2. Conservá la frase original: citala textualmente entre comillas al menos una \
vez, sin alterar sus palabras.
3. Usá SOLO UNA O DOS referencias del perfil, no todas. Rotá: a veces el fútbol, \
a veces un anime, a veces correr, a veces el trabajo o el libro. Amontonar \
referencias suena a plantilla.
4. La referencia debe iluminar la idea de la frase, no ser un adorno pegado. Si \
mencionás un anime, que sea por algo que de verdad pasa en esa historia.
5. Tono: cálido y directo, como un amigo que te escribe. Nada de coaching \
motivacional genérico, nada de "¡Vamos campeón!", nada de hashtags.
6. No inventes hechos sobre su vida (ascensos, partidos, lesiones, planes).
7. Terminá con una idea aplicable a hoy, no con una moraleja abstracta.
8. Devolvé ÚNICAMENTE el texto del mensaje. Sin títulos, sin viñetas, sin \
emojis, sin comillas envolviendo todo, sin explicar lo que hiciste.
"""


class GeminiError(RuntimeError):
    """Error irrecuperable al hablar con Gemini."""


class GeminiPersonalizador:
    """Cliente de Gemini especializado en personalizar frases del corpus."""

    def __init__(
        self,
        api_key: str,
        modelo: str | None = None,
        max_reintentos: int | None = None,
    ) -> None:
        self.modelo = modelo or config.GEMINI_MODEL
        self.max_reintentos = max_reintentos or config.GEMINI_MAX_REINTENTOS
        try:
            self._client = genai.Client(api_key=api_key)
        except Exception as exc:  # noqa: BLE001 - el SDK lanza tipos variados
            raise GeminiError(f"No se pudo inicializar el cliente de Gemini: {exc}") from exc

    # ------------------------------------------------------------------ API
    def personalizar(self, frase: dict[str, Any]) -> tuple[str, bool]:
        """
        Genera la versión personalizada de una frase.

        Returns:
            (texto, uso_gemini) — `uso_gemini=False` significa que se usó el
            fallback local porque la API falló.
        """
        prompt = self._construir_prompt(frase)
        logger.debug("Prompt enviado a Gemini:\n%s", prompt)

        try:
            texto = self._generar_con_reintentos(prompt)
            texto = self._limpiar(texto)
            if len(texto.split()) < 15:
                raise GeminiError("Respuesta demasiado corta para ser útil.")
            logger.info(
                "Personalización generada por Gemini (%s): %d palabras.",
                self.modelo,
                len(texto.split()),
            )
            return texto, True
        except Exception as exc:  # noqa: BLE001
            logger.error("Gemini falló definitivamente: %s", exc)
            logger.warning("Se usa el mensaje de respaldo local.")
            return mensaje_respaldo(frase), False

    # --------------------------------------------------------------- interno
    def _construir_prompt(self, frase: dict[str, Any]) -> str:
        # Se le sugiere un ángulo distinto cada día para forzar variedad.
        angulos = [
            "el trabajo en el banco y las decisiones bajo presión",
            "correr: el ritmo, la constancia, los kilómetros feos",
            "programar: depurar, iterar, romper y volver a construir",
            f"el {config.PERFIL['equipo']} y lo que enseña seguir a un equipo",
            f"algo del libro «{config.PERFIL['lectura_actual']}»",
            "un personaje o momento concreto de alguno de sus animes favoritos",
        ]
        angulo = random.choice(angulos)

        contexto_fuente = {
            "cita_textual": "Es una cita textual de una obra de dominio público; respetá su literalidad.",
            "mensaje_original": "Es un mensaje original de tono lúdico, estilo libro infantil.",
            "parafraseo_discurso": "Viene de un discurso de graduación parafraseado en clase.",
            "parafraseo": "Es un parafraseo de una idea de ese autor.",
            "cita_atribuida": "Es una cita popularmente atribuida a esa persona.",
            "concepto_clase": "Es un concepto trabajado en clase.",
            "cita_clase": "Es una frase usada en una presentación de clase.",
            "pregunta_reflexion": "Es una pregunta de reflexión; puede quedar abierta.",
        }.get(frase["type"], "")

        return (
            "FRASE DEL DÍA (del corpus «Spark»):\n"
            f'"{frase["text"]}"\n'
            f"— {frase['author']}, {frase['source']}\n"
            f"{contexto_fuente}\n\n"
            "PERFIL DE LA PERSONA:\n"
            f"{config.perfil_como_texto()}\n\n"
            f"ÁNGULO SUGERIDO PARA HOY: {angulo}\n"
            "(Usá ese ángulo solo si encaja de forma natural con la frase; "
            "si lo forzás, elegí otro del perfil.)\n\n"
            "Escribí ahora el mensaje matutino siguiendo todas las reglas."
        )

    def _generar_con_reintentos(self, prompt: str) -> str:
        """Llama a Gemini reintentando con backoff exponencial + jitter."""
        ultimo_error: Exception | None = None

        for intento in range(1, self.max_reintentos + 1):
            try:
                respuesta = self._client.models.generate_content(
                    model=self.modelo,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=1.0,       # variedad entre días
                        top_p=0.95,
                        max_output_tokens=600,
                        # Sin "thinking": más rápido y más barato para esta tarea.
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                texto = (respuesta.text or "").strip()
                if not texto:
                    raise GeminiError(
                        "Gemini devolvió una respuesta vacía "
                        f"(posible filtro de seguridad): {respuesta}"
                    )
                return texto

            except Exception as exc:  # noqa: BLE001
                ultimo_error = exc
                if intento == self.max_reintentos:
                    break
                espera = (2 ** (intento - 1)) * 2 + random.uniform(0, 1)
                logger.warning(
                    "Intento %d/%d con Gemini falló (%s). Reintentando en %.1fs…",
                    intento,
                    self.max_reintentos,
                    exc,
                    espera,
                )
                time.sleep(espera)

        raise GeminiError(
            f"Gemini falló tras {self.max_reintentos} intentos: {ultimo_error}"
        )

    @staticmethod
    def _limpiar(texto: str) -> str:
        """Quita envoltorios que el modelo a veces agrega pese al prompt."""
        texto = texto.strip()
        for cerca in ("```markdown", "```text", "```"):
            if texto.startswith(cerca):
                texto = texto[len(cerca):].strip()
            if texto.endswith("```"):
                texto = texto[:-3].strip()
        # Comillas envolviendo TODO el mensaje (pero no las de la cita interna).
        if len(texto) > 2 and texto[0] in '"“' and texto[-1] in '"”' and texto.count('"') == 2:
            texto = texto[1:-1].strip()
        return texto


def mensaje_respaldo(frase: dict[str, Any]) -> str:
    """
    Mensaje de respaldo cuando Gemini no está disponible.

    Simple, pero suficiente para que el recordatorio diario nunca se pierda.
    """
    nombre = config.PERFIL["nombre_corto"]
    aperturas = [
        f"{nombre}, arrancá el día con esta:",
        f"Para hoy, {nombre}:",
        f"{nombre}, tu recordatorio de la mañana:",
    ]
    return (
        f"{random.choice(aperturas)}\n\n"
        f'"{frase["text"]}"\n\n'
        "Llevátela al día de hoy y aplicala en lo primero que te toque."
    )
