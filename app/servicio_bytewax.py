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
import os

from loguru import logger

from app.config.configuracion import configuracion
from app.procesamiento_bytewax.flujo_bytewax import crear_flujo_procesamiento
from app.database.conector_qdrant import ConectorQdrant
from app.database.conector_rabbitmq import ConectorRabbitMQ


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
        
        # Verificar conexiones a servicios requeridos
        if not self._verificar_servicios():
            logger.error("No se pudo verificar los servicios necesarios. Abortando.")
            return False

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

    def _verificar_servicios(self):
        """
        Verifica que todos los servicios necesarios estén disponibles.
        
        Returns:
            bool: True si todos los servicios están disponibles, False en caso contrario
        """
        # Verificar RabbitMQ
        try:
            rabbitmq = ConectorRabbitMQ()
            if not rabbitmq.conectar():
                logger.error("No se pudo conectar a RabbitMQ")
                return False
            
            # Verificar cola
            cola = configuracion.obtener_rabbitmq_cola_cambios()
            if not rabbitmq.declarar_cola(cola):
                logger.error(f"No se pudo declarar la cola {cola}")
                return False
                
            logger.success(f"Conexión a RabbitMQ establecida, cola '{cola}' verificada")
            rabbitmq.desconectar()
        except Exception as e:
            logger.error(f"Error al verificar RabbitMQ: {e}")
            return False
            
        # Verificar Qdrant
        try:
            qdrant = ConectorQdrant()
            if not qdrant.esta_conectado():
                logger.error("No se pudo conectar a Qdrant")
                return False
                
            logger.success("Conexión a Qdrant establecida")
        except Exception as e:
            logger.error(f"Error al verificar Qdrant: {e}")
            return False
            
        # Verificar Ollama si está habilitado
        if configuracion.obtener("USAR_OLLAMA", "false").lower() == "true":
            try:
                import ollama
                try:
                    respuesta = ollama.list()
                    modelos = respuesta.get("models", [])
                    
                    # Verificar modelo de texto
                    modelo_texto = configuracion.obtener("MODELO_TEXTO", "llama3")
                    modelo_encontrado = any(m.get("name") == modelo_texto for m in modelos)
                    
                    if modelo_encontrado:
                        logger.success(f"Modelo de texto '{modelo_texto}' encontrado en Ollama")
                    else:
                        logger.warning(f"Modelo '{modelo_texto}' no encontrado en Ollama")
                        logger.warning(f"Modelos disponibles: {[m.get('name') for m in modelos]}")
                        
                    # Verificar modelo de embedding si se usa Ollama para embeddings
                    if configuracion.obtener("USAR_OLLAMA_EMBEDDINGS", "false").lower() == "true":
                        modelo_embedding = configuracion.obtener("MODELO_EMBEDDING", "all-MiniLM-L6-v2")
                        modelo_emb_encontrado = any(m.get("name") == modelo_embedding for m in modelos)
                        
                        if modelo_emb_encontrado:
                            logger.success(f"Modelo de embedding '{modelo_embedding}' encontrado en Ollama")
                        else:
                            logger.warning(f"Modelo de embedding '{modelo_embedding}' no encontrado en Ollama")
                    
                except Exception as e:
                    logger.warning(f"Error al listar modelos de Ollama: {e}")
                    logger.warning("El procesamiento puede fallar si los modelos no están disponibles")
            except ImportError:
                logger.warning("Ollama está habilitado pero el módulo 'ollama' no está instalado")
                logger.warning("Instale el módulo con: pip install ollama")
                
        logger.success("Todos los servicios verificados correctamente")
        return True

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
    
    # Verificar si se debe mantener el contenedor en ejecución
    keep_alive = os.environ.get("BYTEWAX_KEEP_CONTAINER_ALIVE", "false").lower() == "true"
    
    if keep_alive:
        # Crear e iniciar servicio (modo servicio)
        logger.info("Iniciando en modo servicio (keep-alive)")
        servicio = ServicioBytewax()
        servicio.iniciar()
    else:
        # Modo bytewax.run directo
        logger.info("Iniciando en modo bytewax.run directo")
        
        # Importar después para no afectar el tiempo de inicio
        python_file_path = os.environ.get("BYTEWAX_PYTHON_FILE_PATH", "app.procesamiento_bytewax.flujo_bytewax:flow")
        
        logger.info(f"Iniciando bytewax.run con módulo: {python_file_path}")
        
        # Esta forma de ejecutar requiere que los otros servicios ya estén en ejecución
        # y que la variable BYTEWAX_PYTHON_FILE_PATH apunte a un módulo válido con la variable 'flow'
        
        try:
            from bytewax.run import cli_main
            module_name, attr_name = python_file_path.split(":")
            # Usando sys.argv para pasar argumentos a bytewax.run
            sys.argv = [sys.argv[0], module_name, "-w", "1"]
            cli_main()
        except Exception as e:
            logger.error(f"Error ejecutando bytewax.run: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
