#!/usr/bin/env python
"""
Servicio de procesamiento en tiempo real con ByteWax.

Este script inicia un servicio que procesa los mensajes de RabbitMQ
utilizando ByteWax para transformar los documentos de texto y guardarlos
en Qdrant.
"""

import sys
import signal
import time

from loguru import logger

from app.config.configuracion import configuracion
from app.procesamiento_bytewax.flujo_bytewax import crear_flujo_procesamiento


class ServicioBytewax:
    """
    Servicio principal de procesamiento con ByteWax.

    Esta clase encapsula la lógica del servicio ByteWax que procesa
    mensajes de RabbitMQ y los guarda en Qdrant.
    """

    def __init__(self):
        """Inicializa el servicio ByteWax."""
        # Control de señales
        self.terminando = False
        self.flujo = None
        signal.signal(signal.SIGINT, self._handler_terminar)
        signal.signal(signal.SIGTERM, self._handler_terminar)

    def iniciar(self):
        """Inicia el servicio ByteWax."""
        logger.info("Iniciando servicio ByteWax...")

        try:
            # Crear flujo ByteWax
            self.flujo = crear_flujo_procesamiento()
            
            # Mantener el servicio ejecutándose
            while not self.terminando:
                # Verificar estado del flujo periodicamente
                if self.flujo.hilo_ejecucion and not self.flujo.hilo_ejecucion.is_alive():
                    logger.warning("Hilo de ByteWax terminó, reiniciando...")
                    self.flujo = crear_flujo_procesamiento()
                time.sleep(5)
                
        except KeyboardInterrupt:
            logger.info("Interrupción de teclado detectada")
            self.terminando = True
        except Exception as e:
            logger.error(f"Error en el servicio ByteWax: {e}")
        finally:
            self.detener()

    def detener(self):
        """Detiene el servicio ByteWax."""
        logger.info("Deteniendo servicio ByteWax...")
        
        # Detener flujo ByteWax si existe
        if self.flujo:
            try:
                self.flujo.detener()
            except Exception as e:
                logger.error(f"Error al detener el flujo ByteWax: {e}")
                
        logger.info("Servicio ByteWax detenido")

    def _handler_terminar(self, signum, frame):
        """Manejador de señales para terminar el servicio."""
        logger.info(f"Recibida señal de terminación ({signum})")
        self.terminando = True


def main():
    """Función principal para iniciar el servicio ByteWax."""
    # Configurar logging
    logger.remove()
    logger.add(
        sys.stderr,
        level=configuracion.obtener_nivel_log(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # Crear e iniciar servicio
    servicio = ServicioBytewax()
    servicio.iniciar()


if __name__ == "__main__":
    main()
