from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
import threading
import json
from datetime import datetime
from bytewax.dataflow import Dataflow
from bytewax.inputs import DynamicSource, StatelessSourcePartition
from bytewax.outputs import DynamicSink, StatelessSinkPartition
import bytewax.operators as op
from loguru import logger

from app.database.conector_qdrant import ConectorQdrant
from app.database.conector_rabbitmq import ConectorRabbitMQ
from app.config.configuracion import configuracion
from app.procesamiento_bytewax.dispatchers import (
    ProcesadorDocumentoDispatcher,
    GeneradorEmbeddingsDispatcher
)

class RabbitMQSource(DynamicSource):
    """Fuente de datos desde RabbitMQ."""
    
    def build(self, step_id: str, worker_index: int, worker_count: int) -> StatelessSourcePartition:
        """
        Construye una partición de la fuente para un worker.
        
        Args:
            step_id: ID del paso
            worker_index: Índice del worker actual
            worker_count: Número total de workers
            
        Returns:
            Partición de la fuente
        """
        # Obtener conexión RabbitMQ
        rabbitmq = ConectorRabbitMQ(
            host=configuracion.obtener_rabbitmq_host(),
            puerto=configuracion.obtener_rabbitmq_puerto(),
            usuario=configuracion.obtener_rabbitmq_usuario(),
            contraseña=configuracion.obtener_rabbitmq_contraseña()
        )
        
        if not rabbitmq.conectar():
            logger.error("No se pudo conectar a RabbitMQ en RabbitMQSource")
            raise Exception("Error de conexión a RabbitMQ")
            
        canal = rabbitmq.conexion.channel()
        cola = configuracion.obtener_rabbitmq_cola_cambios()
        
        # Declarar cola
        if not rabbitmq.declarar_cola(cola):
            logger.error(f"No se pudo declarar la cola {cola} en RabbitMQSource")
            raise Exception(f"Error declarando cola {cola}")
            
        # Configurar consumo básico
        canal.basic_qos(prefetch_count=1)
        
        class RabbitMQPartition(StatelessSourcePartition):
            """Partición para consumir mensajes de RabbitMQ."""
            
            def __init__(self, canal, cola):
                self.canal = canal
                self.cola = cola
                
            def next_batch(self) -> List[Any]:
                """Obtiene el siguiente lote de mensajes."""
                try:
                    method_frame, header_frame, body = self.canal.basic_get(queue=self.cola)
                    if method_frame:
                        try:
                            mensaje = json.loads(body.decode("utf-8"))
                            # Confirmar procesamiento
                            self.canal.basic_ack(delivery_tag=method_frame.delivery_tag)
                            return [mensaje]
                        except Exception as e:
                            logger.error(f"Error procesando mensaje: {e}")
                            self.canal.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                    return []
                except Exception as e:
                    logger.error(f"Error en next_batch: {e}")
                    return []
                    
            def next_awake(self) -> Optional[datetime]:
                """Indica cuándo despertar para el siguiente lote."""
                return None  # Procesar inmediatamente
                
            def close(self):
                """Cierra la conexión."""
                try:
                    if self.canal:
                        self.canal.close()
                except Exception as e:
                    logger.error(f"Error cerrando canal: {e}")
        
        return RabbitMQPartition(canal, cola)

@dataclass
class FlujoByteWax:
    """Clase que encapsula el flujo de procesamiento ByteWax."""
    
    flujo: Optional[Dataflow] = None
    hilo_ejecucion: Optional[threading.Thread] = None
    evento_detener: Optional[threading.Event] = None
    
    def __init__(self):
        """Inicializa el flujo ByteWax."""
        self.evento_detener = threading.Event()
        self.flujo = None
        self.hilo_ejecucion = None
        
    def detener(self):
        """Detiene el flujo ByteWax de forma segura."""
        if self.evento_detener:
            logger.info("Iniciando detención del flujo ByteWax...")
            self.evento_detener.set()
            
        if self.hilo_ejecucion and self.hilo_ejecucion.is_alive():
            try:
                self.hilo_ejecucion.join(timeout=5.0)
                logger.info("Flujo ByteWax detenido")
            except Exception as e:
                logger.error(f"Error al detener hilo de ejecución ByteWax: {e}")
                # Intentar forzar terminación del hilo
                if hasattr(threading, "_shutdown"):
                    threading._shutdown()
                    logger.info("Shutdown de threads forzado")

def procesar_documento(mensaje: Dict[str, Any]) -> Dict[str, Any]:
    """
    Procesa un documento usando el dispatcher.
    
    Args:
        mensaje: Mensaje con el documento a procesar
        
    Returns:
        Documento procesado
    """
    try:
        # Crear dispatcher para procesamiento
        dispatcher = ProcesadorDocumentoDispatcher()
        
        # Procesar documento
        documento_procesado = dispatcher.procesar(mensaje)
        
        # Generar embeddings
        dispatcher_embeddings = GeneradorEmbeddingsDispatcher()
        documento_con_embeddings = dispatcher_embeddings.procesar(documento_procesado)
        
        return documento_con_embeddings
        
    except Exception as e:
        logger.error(f"Error procesando documento: {e}")
        return None

class QdrantSink(DynamicSink):
    """Sink para guardar en Qdrant."""
    
    def build(self, step_id: str, worker_index: int, worker_count: int) -> StatelessSinkPartition:
        """
        Construye una partición del sink para un worker.
        
        Args:
            step_id: ID del paso
            worker_index: Índice del worker actual
            worker_count: Número total de workers
            
        Returns:
            Partición del sink
        """
        class QdrantPartition(StatelessSinkPartition):
            """Partición para escribir en Qdrant."""
            
            def __init__(self):
                self.qdrant = ConectorQdrant()
                
            def write_batch(self, items: List[Any]):
                """Escribe un lote de items en Qdrant."""
                for item in items:
                    if item:
                        try:
                            self.qdrant.guardar_documento(item)
                        except Exception as e:
                            logger.error(f"Error guardando en Qdrant: {e}")
                            
            def close(self):
                """Cierra la conexión."""
                pass
                
        return QdrantPartition()

# Crear el flujo de procesamiento (variables a nivel de módulo)
logger.info("Inicializando flujo ByteWax...")
flow = Dataflow("procesamiento_documentos")
input_stream = op.input("input", flow, RabbitMQSource())
processed_stream = op.map("procesar", input_stream, procesar_documento)
op.output("output", processed_stream, QdrantSink())

def crear_flujo_procesamiento() -> FlujoByteWax:
    """
    Crea el flujo de procesamiento ByteWax.
    
    Returns:
        Instancia de FlujoByteWax configurada
    """
    flujo_bytewax = FlujoByteWax()
    
    # Usar flujo definido a nivel de módulo para permitir bytewax.run
    flujo_bytewax.flujo = flow
    
    # Ejecutar en thread separado
    def ejecutar_flujo():
        process = None
        fd = None
        temp_path = None
        
        try:
            import os
            import tempfile
            import atexit
            import subprocess
            import sys
            import signal
            
            # Crear un archivo temporal que contenga nuestro dataflow
            fd, temp_path = tempfile.mkstemp(suffix='.py')
            
            # Asegurarse de que el archivo temporal se elimine al salir
            def cleanup():
                try:
                    if fd is not None:
                        os.close(fd)
                except (OSError, IOError) as e:
                    logger.warning(f"No se pudo cerrar el descriptor de archivo: {e}")
                    
                try:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                except (OSError, IOError) as e:
                    logger.warning(f"No se pudo eliminar el archivo temporal: {e}")
            
            atexit.register(cleanup)
            
            # Contenido del script temporal
            script_contenido = f"""
import bytewax.operators as op
from bytewax.dataflow import Dataflow
import sys
import os

# Añadir la ruta base del proyecto al path
sys.path.insert(0, "{os.getcwd()}")

# Importar nuestras clases
from app.procesamiento_bytewax.flujo_bytewax import RabbitMQSource, QdrantSink, procesar_documento

# Crear el mismo flujo que tenemos en memoria
flow = Dataflow("procesamiento_documentos")
input_stream = op.input("input", flow, RabbitMQSource())
processed_stream = op.map("procesar", input_stream, procesar_documento)
op.output("output", processed_stream, QdrantSink())

# Variable global para que bytewax.run pueda encontrarla
dataflow = flow
"""
            
            # Escribir el contenido al archivo temporal
            with os.fdopen(fd, 'w') as f:
                f.write(script_contenido)
                # El descriptor de archivo se cerrará automáticamente al salir del with
                fd = None
            
            # Ejecutar el flujo como un módulo
            cmd = [
                sys.executable, "-m", "bytewax.run",
                temp_path.replace(".py", ""),
                "-w", "1",  # Un worker por proceso
            ]
            
            logger.info(f"Ejecutando ByteWax con comando: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True  # Crear un nuevo grupo de procesos
            )
            
            # Monitorear si debemos detener el proceso
            while not flujo_bytewax.evento_detener.is_set():
                # Verificar si el proceso sigue vivo
                if process.poll() is not None:
                    logger.warning("El proceso ByteWax terminó inesperadamente")
                    # Capturar salida de error
                    _, stderr = process.communicate()
                    if stderr:
                        logger.error(f"Error en el proceso ByteWax: {stderr.decode('utf-8', errors='replace')}")
                    break
                # Dormir un poco para no consumir CPU
                flujo_bytewax.evento_detener.wait(timeout=1.0)
                
            # Intentar terminar el proceso si sigue vivo
            if process and process.poll() is None:
                logger.info("Terminando proceso ByteWax")
                try:
                    # Enviar señal SIGTERM al grupo de procesos
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    # Esperar a que termine
                    process.wait(timeout=5.0)
                except (subprocess.TimeoutExpired, ProcessLookupError) as e:
                    logger.warning(f"No se pudo terminar el proceso normalmente: {e}")
                    try:
                        # Intentar matar forzadamente
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        # El proceso ya no existe
                        pass
                    except Exception as e:
                        logger.error(f"Error al terminar proceso: {e}")
                
        except Exception as e:
            logger.error(f"Error en flujo ByteWax: {e}")
        finally:
            # Limpiar recursos
            try:
                # Limpiar el archivo temporal
                if fd is not None:
                    os.close(fd)
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
                
                # Asegurarse de que el proceso está terminado
                if process and process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=1.0)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Error al limpiar recursos: {e}")
            
    flujo_bytewax.hilo_ejecucion = threading.Thread(target=ejecutar_flujo)
    flujo_bytewax.hilo_ejecucion.start()
    
    return flujo_bytewax