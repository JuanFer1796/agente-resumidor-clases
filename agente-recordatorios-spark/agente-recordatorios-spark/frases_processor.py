"""
frases_processor.py
===================
Lectura del corpus Spark y selección de la frase del día.

Incluye un historial (`historial.json`) para no repetir las frases enviadas
recientemente: con ~73 frases, una selección puramente aleatoria repetiría
en cuestión de días.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

CAMPOS_REQUERIDOS = ("id", "source", "author", "text", "type", "license")


class CorpusError(RuntimeError):
    """Problemas al leer o validar el corpus."""


class FrasesProcessor:
    """Carga el corpus, valida su estructura y elige la frase del día."""

    def __init__(
        self,
        corpus_path: Path | None = None,
        historial_path: Path | None = None,
        historial_max: int | None = None,
    ) -> None:
        self.corpus_path = corpus_path or config.CORPUS_PATH
        self.historial_path = historial_path or config.HISTORIAL_PATH
        self.historial_max = historial_max or config.HISTORIAL_MAX
        self.frases: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- corpus
    def cargar_corpus(self) -> list[dict[str, Any]]:
        """Lee corpus_frases.json y valida cada entrada."""
        if not self.corpus_path.exists():
            raise CorpusError(
                f"No se encontró el corpus en {self.corpus_path}. "
                "Verificá que corpus_frases.json esté en la raíz del repo."
            )

        try:
            datos = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CorpusError(f"corpus_frases.json no es JSON válido: {exc}") from exc

        if not isinstance(datos, list) or not datos:
            raise CorpusError("El corpus debe ser una lista JSON no vacía.")

        validas: list[dict[str, Any]] = []
        for i, item in enumerate(datos):
            if not isinstance(item, dict):
                logger.warning("Entrada #%d ignorada: no es un objeto JSON.", i)
                continue
            faltan = [c for c in CAMPOS_REQUERIDOS if not item.get(c)]
            if faltan:
                logger.warning(
                    "Entrada #%d (id=%s) ignorada: faltan campos %s.",
                    i,
                    item.get("id", "?"),
                    faltan,
                )
                continue
            validas.append(item)

        if not validas:
            raise CorpusError("Ninguna entrada del corpus pasó la validación.")

        self.frases = validas
        logger.info(
            "Corpus cargado: %d frases válidas de %d entradas. Fuentes: %s",
            len(validas),
            len(datos),
            ", ".join(f"{k} ({v})" for k, v in self.resumen_fuentes().items()),
        )
        return self.frases

    def resumen_fuentes(self) -> dict[str, int]:
        """Cuenta cuántas frases hay por fuente (para estadísticas/logs)."""
        conteo: dict[str, int] = {}
        for f in self.frases:
            conteo[f["source"]] = conteo.get(f["source"], 0) + 1
        return dict(sorted(conteo.items(), key=lambda kv: -kv[1]))

    # ------------------------------------------------------------- historial
    def _leer_historial(self) -> dict[str, Any]:
        if not self.historial_path.exists():
            return {"enviadas": [], "total_enviados": 0}
        try:
            data = json.loads(self.historial_path.read_text(encoding="utf-8"))
            data.setdefault("enviadas", [])
            data.setdefault("total_enviados", 0)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Historial ilegible (%s). Se empieza de cero.", exc)
            return {"enviadas": [], "total_enviados": 0}

    def registrar_envio(self, frase: dict[str, Any]) -> None:
        """Guarda la frase enviada en el historial (se llama tras un envío OK)."""
        data = self._leer_historial()
        registro = {
            "id": frase["id"],
            "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        data["enviadas"] = ([registro] + data["enviadas"])[: self.historial_max]
        data["total_enviados"] = int(data["total_enviados"]) + 1
        try:
            self.historial_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info(
                "Historial actualizado: %s (envío #%d).",
                frase["id"],
                data["total_enviados"],
            )
        except OSError as exc:
            logger.warning("No se pudo escribir el historial: %s", exc)

    def estadisticas(self) -> dict[str, Any]:
        """Métricas simples para el log de cada corrida."""
        data = self._leer_historial()
        return {
            "frases_en_corpus": len(self.frases),
            "recordatorios_enviados": data["total_enviados"],
            "ids_recientes": [e["id"] for e in data["enviadas"][:5]],
        }

    # -------------------------------------------------------------- selección
    def seleccionar_aleatoria(self, evitar_repetidas: bool = True) -> dict[str, Any]:
        """
        Elige una frase al azar, evitando las últimas `historial_max` enviadas.

        Si todas las frases están en el historial (corpus pequeño), se relaja
        la restricción y se elige entre todas.
        """
        if not self.frases:
            self.cargar_corpus()

        candidatas = self.frases
        if evitar_repetidas:
            recientes = {e["id"] for e in self._leer_historial()["enviadas"]}
            disponibles = [f for f in self.frases if f["id"] not in recientes]
            if disponibles:
                candidatas = disponibles
            else:
                logger.info("Todas las frases son recientes; se reinicia el ciclo.")

        # random.SystemRandom evita cualquier sesgo por semilla heredada.
        frase = random.SystemRandom().choice(candidatas)
        logger.info(
            "Frase seleccionada: id=%s | fuente=%s | tipo=%s (%d candidatas)",
            frase["id"],
            frase["source"],
            frase["type"],
            len(candidatas),
        )
        return frase

    def obtener_por_id(self, frase_id: str) -> dict[str, Any]:
        """Devuelve una frase concreta (útil para pruebas con --id)."""
        if not self.frases:
            self.cargar_corpus()
        for f in self.frases:
            if f["id"] == frase_id:
                return f
        raise CorpusError(f"No existe ninguna frase con id='{frase_id}'.")

    @staticmethod
    def obtener_metadatos(frase: dict[str, Any]) -> dict[str, str]:
        """Extrae los metadatos de atribución de una frase."""
        return {
            "id": frase["id"],
            "source": frase["source"],
            "author": frase["author"],
            "type": frase["type"],
            "license": frase["license"],
        }
