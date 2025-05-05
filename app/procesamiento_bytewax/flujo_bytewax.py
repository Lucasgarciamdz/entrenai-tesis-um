"""
Implementación del flujo de procesamiento con ByteWax.

Este módulo define el flujo de procesamiento para transformar documentos
de texto a embeddings y guardarlos en la base de datos vectorial.
"""

from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
import threading
import json
import time
import uuid
from datetime import datetime
import sys

import bytewax.operators as op
from bytewax.dataflow import Dataflow
from bytewax.inputs import FixedPartitionedSource, StatefulSourcePartition
from bytewax.outputs import DynamicSink, StatelessSinkPartition
from loguru import logger

from app.database.conector_qdrant import ConectorQdrant
from app.database.conector_rabbitmq import ConectorRabbitMQ
from app.config.configuracion import configuracion
from app.procesamiento_bytewax.dispatchers import (
    ProcesadorDocumentoDispatcher,
    GeneradorEmbeddingsDispatcher
)

class RabbitMQPartition(StatefulSourcePartition):
    """
    Partición para consumir mensajes de RabbitMQ.
    Implementa la interfaz StatefulSourcePartition para permitir
    el seguimiento del estado y recuperación en caso de fallos.
    """
    
    def __init__(self, queue_name: str, resume_state: Any = None):
        """
        Inicializa la partición de RabbitMQ.
        
        Args:
            queue_name: Nombre de la cola a consumir
            resume_state: Estado para recuperar (IDs de mensajes en vuelo)
        """
        self._in_flight_msg_ids = resume_state or set()
        self.queue_name = queue_name
        # Crear conexión a RabbitMQ
        self.connection = ConectorRabbitMQ(
            host=configuracion.obtener_rabbitmq_host(),
            puerto=configuracion.obtener_rabbitmq_puerto(),
            usuario=configuracion.obtener_rabbitmq_usuario(),
            contraseña=configuracion.obtener_rabbitmq_contraseña()
        )
        self.connection.conectar()
        self.channel = self.connection.conexion.channel()
        self.connection.declarar_cola(self.queue_name)
        
    def next_batch(self, sched: Optional[datetime]) -> List[Any]:
        """
        Obtiene el siguiente lote de mensajes de la cola.
        
        Args:
            sched: Timestamp programado para el próximo procesamiento
            
        Returns:
            Lista con los mensajes recibidos
        """
        try:
            method_frame, header_frame, body = self.channel.basic_get(
                queue=self.queue_name, auto_ack=False
            )
        except Exception as e:
            logger.error(f"Error al obtener mensaje de RabbitMQ: {e}")
            try:
                # Intentar reconexión
                time.sleep(5)
                self.connection.conectar()
                self.channel = self.connection.conexion.channel()
                self.connection.declarar_cola(self.queue_name)
            except Exception as reconnect_err:
                logger.error(f"Error al reconectar a RabbitMQ: {reconnect_err}")
            return []

        if method_frame:
            message_id = method_frame.delivery_tag
            self._in_flight_msg_ids.add(message_id)
            
            try:
                mensaje = json.loads(body)
                logger.info(f"Mensaje recibido de RabbitMQ: operación {mensaje.get('operationType', 'desconocida')}")
                return [mensaje]
            except Exception as e:
                logger.error(f"Error al procesar mensaje de RabbitMQ: {e}")
                # Rechazar mensaje con requeue=False para evitar ciclos infinitos
                self.channel.basic_nack(delivery_tag=message_id, requeue=False)
                self._in_flight_msg_ids.remove(message_id)
                return []
        else:
            return []
    
    def snapshot(self) -> Any:
        """
        Obtiene un snapshot del estado actual para permitir recuperación.
        
        Returns:
            Estado actual (IDs de mensajes en vuelo)
        """
        return self._in_flight_msg_ids
    
    def garbage_collect(self, state):
        """
        Confirma los mensajes procesados correctamente.
        
        Args:
            state: Estado de los mensajes procesados
        """
        closed_in_flight_msg_ids = state
        for msg_id in closed_in_flight_msg_ids:
            try:
                self.channel.basic_ack(delivery_tag=msg_id)
                self._in_flight_msg_ids.remove(msg_id)
            except Exception as e:
                logger.error(f"Error al confirmar mensaje {msg_id}: {e}")
    
    def close(self):
        """Cierra la conexión a RabbitMQ."""
        try:
            if self.channel and self.channel.is_open:
                self.channel.close()
        except Exception as e:
            logger.error(f"Error al cerrar canal RabbitMQ: {e}")

class RabbitMQSource(FixedPartitionedSource):
    """
    Fuente de datos desde RabbitMQ.
    Implementa FixedPartitionedSource para definir una única partición
    que consume de la cola.
    """
    
    def list_parts(self) -> List[str]:
        """
        Lista las particiones disponibles.
        
        Returns:
            Lista con una única partición
        """
        return ["single_partition"]
    
    def build_part(self, now: datetime, for_part: str, resume_state: Any = None) -> StatefulSourcePartition:
        """
        Construye una partición para la fuente.
        
        Args:
            now: Timestamp actual
            for_part: Nombre de la partición
            resume_state: Estado para recuperación
            
        Returns:
            Partición configurada
        """
        cola = configuracion.obtener_rabbitmq_cola_cambios()
        return RabbitMQPartition(queue_name=cola, resume_state=resume_state)

def procesar_documento(mensaje: Dict[str, Any]) -> Dict[str, Any]:
    """
    Procesa un documento usando los dispatchers.
    Transforma el documento a markdown y genera embeddings.
    
    Args:
        mensaje: Mensaje con el documento a procesar
        
    Returns:
        Documento procesado con embeddings
    """
    try:
        # Crear dispatcher para procesamiento
        dispatcher = ProcesadorDocumentoDispatcher()
        
        # Procesar documento (limpieza y transformación a markdown)
        documento_procesado = dispatcher.procesar(mensaje)
        if documento_procesado is None:
            logger.warning("Documento no pudo ser procesado")
            return None
        
        # Generar embeddings
        dispatcher_embeddings = GeneradorEmbeddingsDispatcher()
        documento_con_embeddings = dispatcher_embeddings.procesar(documento_procesado)
        if documento_con_embeddings is None:
            logger.warning("No se pudieron generar embeddings para el documento")
            return documento_procesado  # Devolver al menos el documento procesado
        
        logger.success("Documento procesado correctamente con embeddings")
        return documento_con_embeddings
        
    except Exception as e:
        logger.error(f"Error procesando documento: {e}")
        return None

class QdrantPartition(StatelessSinkPartition):
    """
    Partición para guardar datos en Qdrant.
    """
    
    def __init__(self):
        """Inicializa la conexión con Qdrant."""
        self.qdrant = ConectorQdrant()
        
    def write_batch(self, items: List[Any]):
        """
        Escribe un lote de items en Qdrant.
        
        Args:
            items: Lista de documentos a guardar
        """
        for item in items:
            if not item:
                continue
                
            try:
                # Verificar si el item tiene chunks
                if "chunks" in item and item["chunks"]:
                    # Obtener información del documento
                    id_curso = item.get("id_curso")
                    if not id_curso:
                        logger.warning("Documento sin id_curso, usando colección default")
                        coleccion = configuracion.obtener("QDRANT_COLECCION_DEFAULT", "documentos")
                    else:
                        # Usar prefijo para colección de curso
                        prefijo = configuracion.obtener("QDRANT_COLLECTION_PREFIX", "curso_")
                        coleccion = f"{prefijo}{id_curso}"
                    
                    # Verificar/crear colección
                    if not self.qdrant.esta_conectado():
                        logger.error("No se pudo conectar a Qdrant")
                        continue
                        
                    # Verificar si la colección existe, si no, crearla
                    if coleccion not in self.qdrant.colecciones_existentes:
                        # Obtener dimensión del primer embedding si existe
                        dimension = None
                        if item["chunks"] and "embedding" in item["chunks"][0]:
                            dimension = len(item["chunks"][0]["embedding"])
                        
                        if not dimension:
                            dimension = int(configuracion.obtener("QDRANT_DIMENSION_EMBEDDINGS", "384"))
                            
                        logger.info(f"Creando colección {coleccion} con dimensión {dimension}")
                        if not self.qdrant.crear_coleccion(coleccion, dimension):
                            logger.error(f"No se pudo crear la colección {coleccion}")
                            continue
                            
                        # Actualizar cache de colecciones
                        self.qdrant.colecciones_existentes.add(coleccion)
                    
                    # Guardar cada chunk como un punto separado
                    for chunk in item["chunks"]:
                        if "embedding" not in chunk:
                            logger.warning(f"Chunk sin embedding, saltando")
                            continue
                            
                        # Preparar metadatos
                        metadatos = {
                            "id_original": item.get("id_original", item.get("id", "")),
                            "id_curso": id_curso,
                            "nombre_curso": item.get("nombre_curso", ""),
                            "texto": chunk["texto"],
                            "contexto": chunk.get("contexto", ""),
                            "indice_chunk": chunk.get("indice", 0),
                            "total_chunks": chunk.get("total", 1),
                            "tipo_contenido": item.get("tipo_contenido", "texto"),
                            "formato": item.get("formato", "markdown")
                        }
                        
                        # Añadir otros metadatos del documento original
                        for clave, valor in item.get("metadatos", {}).items():
                            if clave not in metadatos:
                                metadatos[clave] = valor
                        
                        # Crear ID único para el punto
                        id_punto = f"{item.get('id', uuid.uuid4().hex)}_{chunk.get('indice', 0)}"
                        
                        # Guardar punto en Qdrant
                        self.qdrant.guardar_embedding(
                            id_embedding=id_punto,
                            texto=chunk["texto"],
                            embedding=chunk["embedding"],
                            texto_original_id=item.get("id_original", item.get("id", "")),
                            metadatos=metadatos,
                            coleccion=coleccion
                        )
                        
                    logger.success(f"Guardados {len(item['chunks'])} chunks en colección {coleccion}")
                else:
                    # Documento sin chunks, guardar como documento completo
                    logger.info("Documento sin chunks, guardando como documento completo")
                    # Implementación similar pero con el documento completo
            except Exception as e:
                logger.error(f"Error guardando documento en Qdrant: {e}")
    
    def close(self):
        """Cierra la conexión con Qdrant."""
        pass

class QdrantSink(DynamicSink):
    """
    Sink para guardar datos en Qdrant.
    """
    
    def build(self, worker_index: int, worker_count: int) -> StatelessSinkPartition:
        """
        Construye una partición del sink.
        
        Args:
            worker_index: Índice del worker
            worker_count: Número total de workers
            
        Returns:
            Partición configurada
        """
        return QdrantPartition()

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
    
    def iniciar(self):
        """Inicia el flujo ByteWax en un hilo separado."""
        if self.hilo_ejecucion and self.hilo_ejecucion.is_alive():
            logger.warning("El flujo ByteWax ya está en ejecución")
            return False
            
        self.evento_detener.clear()
        
        # Crear e iniciar el hilo de ejecución
        self.hilo_ejecucion = threading.Thread(
            target=self._ejecutar_flujo,
            daemon=True
        )
        self.hilo_ejecucion.start()
        
        logger.info("Flujo ByteWax iniciado en segundo plano")
        return True
        
    def _ejecutar_flujo(self):
        """Ejecuta el flujo ByteWax."""
        try:
            # Crear el flujo
            import uuid
            from bytewax.run import cli_main
            import importlib
            
            # Configurar el flujo
            flow = Dataflow("procesamiento_documentos")
            input_stream = op.input("input", flow, RabbitMQSource())
            filtered_stream = op.filter_map("filtrar", input_stream, lambda x: x)
            processed_stream = op.map("procesar", filtered_stream, procesar_documento)
            filtered_processed = op.filter_map("filtrar_procesados", processed_stream, lambda x: x)
            op.output("output", filtered_processed, QdrantSink())
            
            self.flujo = flow
            
            # Iniciar el flujo (bytewax lo ejecutará)
            logger.info("Iniciando ejecución del flujo ByteWax...")
            
            # Crear módulo temporal con el flujo
            module_name = f"bytewax_flow_{uuid.uuid4().hex}"
            module = type(importlib.util.module_from_spec(importlib.machinery.ModuleSpec(
                name=module_name,
                loader=None
            )))
            
            # Asignar el flujo al módulo
            module.flow = flow
            sys.modules[module_name] = module
            
            # Iniciar procesamiento
            cli_main(module_name)
            
        except Exception as e:
            logger.error(f"Error en la ejecución del flujo ByteWax: {e}")
        finally:
            logger.info("Flujo ByteWax terminado")
        
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

# Función exportada para crear el flujo de procesamiento
def crear_flujo_procesamiento() -> FlujoByteWax:
    """
    Crea e inicia el flujo de procesamiento ByteWax.
    
    Returns:
        Instancia de FlujoByteWax configurada y en ejecución
    """
    flujo_bytewax = FlujoByteWax()
    flujo_bytewax.iniciar()
    return flujo_bytewax