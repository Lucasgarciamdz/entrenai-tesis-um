#!/usr/bin/env python
"""
Servicio de Change Data Capture (CDC) para MongoDB.

Este script inicia un servicio que monitorea cambios en MongoDB y los
publica en una cola de RabbitMQ para su procesamiento por otros servicios.
"""

import os
import sys
import time
import signal
from typing import Optional, List

from loguru import logger

from app.config.configuracion import configuracion
from app.database.cdc_mongodb import crear_monitor_cdc, MonitorCambiosMongoDB


class ServicioCDC:
    """
    Servicio principal de CDC.

    Esta clase encapsula la lógica del servicio CDC que monitorea
    cambios en MongoDB y los publica en RabbitMQ.
    """

    def __init__(
        self,
        nombre_cola: Optional[str] = None,
        colecciones: Optional[List[str]] = None,
        filtro_operaciones: Optional[List[str]] = None,
    ):
        """
        Inicializa el servicio CDC.

        Args:
            nombre_cola: Nombre de la cola de RabbitMQ (opcional)
            colecciones: Lista de colecciones a monitorear (opcional)
            filtro_operaciones: Lista de operaciones a capturar (opcional)
        """
        self.nombre_cola = nombre_cola or configuracion.obtener_rabbitmq_cola_cambios()
        self.colecciones = colecciones
        self.filtro_operaciones = filtro_operaciones

        # Monitor CDC
        self.monitor: Optional[MonitorCambiosMongoDB] = None

        # Control de señales
        self.terminando = False
        signal.signal(signal.SIGINT, self._handler_terminar)
        signal.signal(signal.SIGTERM, self._handler_terminar)

    def iniciar(self):
        """Inicia el servicio CDC."""
        logger.info("Iniciando servicio CDC...")

        # Crear y configurar monitor CDC
        self.monitor = crear_monitor_cdc(
            nombre_cola=self.nombre_cola,
            colecciones=self.colecciones,
            filtro_operaciones=self.filtro_operaciones,
        )

        # Iniciar monitor
        if not self.monitor.iniciar():
            logger.error("No se pudo iniciar el monitor CDC")
            return False

        logger.info(
            f"Servicio CDC iniciado. Monitoreando cambios para cola '{self.nombre_cola}'"
        )

        # Mantener el servicio en ejecución
        try:
            while not self.terminando:
                time.sleep(1)
        except Exception as e:
            logger.error(f"Error en el servicio CDC: {e}")
        finally:
            self.detener()

        return True

    def detener(self):
        """Detiene el servicio CDC."""
        logger.info("Deteniendo servicio CDC...")

        if self.monitor:
            self.monitor.detener()
            self.monitor = None

        logger.info("Servicio CDC detenido")

    def _handler_terminar(self, signum, frame):
        """Manejador de señales para terminar el servicio."""
        logger.info(f"Recibida señal de terminación ({signum})")
        self.terminando = True


def main():
    """Función principal para iniciar el servicio CDC."""
    # Configurar logging
    logger.remove()
    logger.add(
        sys.stderr,
        level=configuracion.obtener_nivel_log(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # Configuración opcional desde variables de entorno
    nombre_cola = os.environ.get("CDC_COLA_NOMBRE")
    colecciones_str = os.environ.get("CDC_COLECCIONES")
    colecciones = colecciones_str.split(",") if colecciones_str else None

    operaciones_str = os.environ.get("CDC_OPERACIONES")
    operaciones = operaciones_str.split(",") if operaciones_str else None

    # Crear e iniciar servicio
    servicio = ServicioCDC(
        nombre_cola=nombre_cola,
        colecciones=colecciones,
        filtro_operaciones=operaciones,
    )

    servicio.iniciar()


if __name__ == "__main__":
    main()
