"""
main.py
=======
Punto de entrada del agente. 100% no interactivo (sin input()).

Códigos de salida:
    0 → el recordatorio se envió (o el dry-run terminó bien)
    1 → algo falló; el detalle está en los logs

Ejemplos:
    python main.py                       # flujo normal
    python main.py --dry-run             # no envía nada, muestra vista previa
    python main.py --id quijote_14       # fuerza una frase específica
    python main.py --sin-gemini          # salta Gemini (prueba solo Telegram)
    python main.py --validar             # solo verifica credenciales y corpus
    python main.py --log-level DEBUG     # más verborrea
"""

from __future__ import annotations

import argparse
import logging
import sys

import config
from orchestrator import Orchestrator


def parsear_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agente-recordatorios-spark",
        description="Envía un recordatorio diario personalizado por Telegram.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecuta todo pero no envía el mensaje; imprime la vista previa.",
    )
    parser.add_argument(
        "--id",
        dest="frase_id",
        metavar="FRASE_ID",
        help="Fuerza una frase concreta del corpus (ej. quijote_14).",
    )
    parser.add_argument(
        "--sin-gemini",
        action="store_true",
        help="Omite la personalización con Gemini y usa el mensaje de respaldo.",
    )
    parser.add_argument(
        "--validar",
        action="store_true",
        help="Solo valida credenciales, conexión a Telegram y corpus. No envía.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Nivel de logging (por defecto el de LOG_LEVEL o INFO).",
    )
    parser.add_argument(
        "--sin-alerta",
        action="store_true",
        help="No manda alerta por Telegram si la corrida falla.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parsear_argumentos(argv)
    logger = logging.getLogger("main")
    config.configurar_logging(args.log_level)

    logger.info("Iniciando agente de recordatorios Spark…")

    # ---------------------------------------------------------- credenciales
    try:
        credenciales = config.cargar_credenciales(requiere_gemini=not args.sin_gemini)
        logger.info("Credenciales cargadas: %s", credenciales.enmascarado())
    except config.ConfigError as exc:
        logger.error("%s", exc)
        logger.error(
            "Si corrés local: copiá .env.example a .env y llenalo. "
            "Si corrés en GitHub Actions: revisá Settings → Secrets → Actions."
        )
        return 1

    orquestador = Orchestrator(
        credenciales=credenciales,
        usar_gemini=not args.sin_gemini,
        dry_run=args.dry_run,
    )

    # ------------------------------------------------------------- validación
    if args.validar:
        logger.info("Modo --validar: comprobando todo sin enviar nada.")
        ok_telegram = orquestador.telegram.validar_conexion()
        try:
            orquestador.procesador.cargar_corpus()
            ok_corpus = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Corpus inválido: %s", exc)
            ok_corpus = False
        logger.info("Telegram: %s | Corpus: %s", "OK" if ok_telegram else "FALLA",
                    "OK" if ok_corpus else "FALLA")
        return 0 if (ok_telegram and ok_corpus) else 1

    # --------------------------------------------------------------- ejecución
    resultado = orquestador.ejecutar(frase_id=args.frase_id)

    if resultado.exito:
        logger.info("Listo. Recordatorio del día completado.")
        return 0

    if not args.sin_alerta:
        orquestador.notificar_error(resultado.error or "Error desconocido.")
    logger.error("La corrida terminó con error.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
