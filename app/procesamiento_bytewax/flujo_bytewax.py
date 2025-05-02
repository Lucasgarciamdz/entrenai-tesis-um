"""
Flujo de procesamiento con ByteWax.

Este módulo define el flujo de procesamiento en tiempo real con ByteWax
que lee mensajes de RabbitMQ, procesa los documentos y los guarda en Qdrant.
"""

import json
from typing import Dict, List, Any

import bytewax.operators as op
from bytewax.dataflow import Dataflow
from bytewax.execution import run_main
from bytewax.connectors.rabbitmq import RabbitMQInput
import pika
from loguru import logger

from ..config.configuracion import configuracion
from ..database.conector_qdrant import conector_qdrant
from .dispatchers import (
    RawDispatcher,
    LimpiezaDispatcher,
    ChunkingDispatcher,
    EmbeddingDispatcher,
)
from .modelos import ModeloRaw, ModeloLimpio, ModeloTrunk, ModeloEmbedding


class EntradaRabbitMQ(RabbitMQInput):
    """
    Entrada personalizada para RabbitMQ.

    Esta clase extiende la funcionalidad de RabbitMQInput de ByteWax
    para adaptarla a nuestras necesidades específicas.
    """

    def __init__(
        self,
        host: str = None,
        puerto: int = None,
        usuario: str = None,
        contraseña: str = None,
        cola: str = None,
        virtual_host: str = "/",
    ):
        """
        Inicializa la entrada de RabbitMQ.

        Args:
            host: Host de RabbitMQ
            puerto: Puerto de RabbitMQ
            usuario: Usuario para autenticarse con RabbitMQ
            contraseña: Contraseña para autenticarse con RabbitMQ
            cola: Nombre de la cola de RabbitMQ
            virtual_host: Virtual host de RabbitMQ
        """
        # Cargar parámetros desde configuración o valores por defecto
        self.host = host or configuracion.obtener("RABBITMQ_HOST", "localhost")
        self.puerto = puerto or int(configuracion.obtener("RABBITMQ_PORT", "5672"))
        self.usuario = usuario or configuracion.obtener("RABBITMQ_USERNAME", "guest")
        self.contraseña = contraseña or configuracion.obtener(
            "RABBITMQ_PASSWORD", "guest"
        )
        self.cola = cola or configuracion.obtener(
            "RABBITMQ_COLA_CAMBIOS", "cambios_mongodb"
        )
        self.virtual_host = virtual_host

        # Configurar parámetros de conexión
        credenciales = pika.PlainCredentials(self.usuario, self.contraseña)
        parametros = pika.ConnectionParameters(
            host=self.host,
            port=self.puerto,
            virtual_host=self.virtual_host,
            credentials=credenciales,
        )

        # Inicializar clase padre
        super().__init__(
            pika_params=parametros,
            queue_name=self.cola,
            deserializer=self._deserializar_mensaje,
        )

    def _deserializar_mensaje(self, body: bytes) -> Dict[str, Any]:
        """
        Deserializa un mensaje de RabbitMQ.

        Args:
            body: Cuerpo del mensaje en bytes

        Returns:
            Mensaje deserializado como diccionario
        """
        try:
            # Decodificar y deserializar
            mensaje = json.loads(body.decode("utf-8"))
            return mensaje
        except Exception as e:
            logger.error(f"Error al deserializar mensaje: {e}")
            return {}


class SalidaQdrant:
    """
    Salida personalizada para Qdrant.

    Esta clase implementa una salida personalizada para ByteWax
    que guarda los datos procesados en Qdrant.
    """

    def __init__(self):
        """Inicializa la salida de Qdrant."""
        # Asegurar conexión con Qdrant
        if not conector_qdrant.esta_conectado():
            conector_qdrant.conectar()

    def escribir_texto_limpio(self, item: ModeloLimpio):
        """
        Escribe un texto limpio en Qdrant.

        Args:
            item: ModeloLimpio a guardar
        """
        conector_qdrant.guardar_texto_limpio(
            id_texto=item.id,
            texto=item.texto_limpio,
            metadatos={
                "tipo": item.tipo,
                "formato_original": item.formato_original,
                "formato_limpio": item.formato_limpio,
                **item.metadatos,
            },
        )

    def escribir_embedding(self, item: ModeloEmbedding):
        """
        Escribe un embedding en Qdrant.

        Args:
            item: ModeloEmbedding a guardar
        """
        conector_qdrant.guardar_embedding(
            id_embedding=item.id,
            texto=item.texto,
            embedding=item.embedding,
            texto_original_id=item.texto_original_id,
            metadatos={
                "tipo": item.tipo,
                "indice": item.indice,
                "contexto": item.contexto,
                "modelo_embedding": item.modelo_embedding,
                **item.metadatos,
            },
        )


def procesar_mensaje_raw(mensaje: Dict[str, Any]) -> ModeloRaw:
    """
    Procesa un mensaje crudo de RabbitMQ y lo convierte a ModeloRaw.

    Args:
        mensaje: Mensaje recibido de RabbitMQ

    Returns:
        ModeloRaw construido a partir del mensaje
    """
    return RawDispatcher.procesar(mensaje)


def limpiar_texto(modelo_raw: ModeloRaw) -> ModeloLimpio:
    """
    Limpia el texto de un ModeloRaw.

    Args:
        modelo_raw: ModeloRaw a procesar

    Returns:
        ModeloLimpio con el texto limpio
    """
    return LimpiezaDispatcher.procesar(modelo_raw)


def guardar_texto_limpio(modelo_limpio: ModeloLimpio) -> ModeloLimpio:
    """
    Guarda un texto limpio en Qdrant y lo devuelve para continuar el procesamiento.

    Args:
        modelo_limpio: ModeloLimpio a guardar

    Returns:
        El mismo ModeloLimpio para continuar el procesamiento
    """
    salida = SalidaQdrant()
    salida.escribir_texto_limpio(modelo_limpio)
    return modelo_limpio


def dividir_en_chunks(modelo_limpio: ModeloLimpio) -> List[ModeloTrunk]:
    """
    Divide el texto de un ModeloLimpio en chunks.

    Args:
        modelo_limpio: ModeloLimpio a procesar

    Returns:
        Lista de ModeloTrunk con los fragmentos del texto
    """
    return ChunkingDispatcher.procesar(modelo_limpio)


def generar_embeddings(modelo_trunk: ModeloTrunk) -> ModeloEmbedding:
    """
    Genera el embedding para un ModeloTrunk.

    Args:
        modelo_trunk: ModeloTrunk a procesar

    Returns:
        ModeloEmbedding con el vector de embedding
    """
    return EmbeddingDispatcher.procesar(modelo_trunk)


def guardar_embedding(modelo_embedding: ModeloEmbedding) -> None:
    """
    Guarda un embedding en Qdrant.

    Args:
        modelo_embedding: ModeloEmbedding a guardar
    """
    salida = SalidaQdrant()
    salida.escribir_embedding(modelo_embedding)


def crear_flujo_bytewax() -> Dataflow:
    """
    Crea el flujo de procesamiento con ByteWax.

    Returns:
        Flujo de ByteWax configurado
    """
    # Crear flujo
    flow = Dataflow()

    # 1. Entrada: leer de RabbitMQ
    entrada = op.input("entrada", flow, EntradaRabbitMQ())

    # 2. Procesar mensaje crudo
    raw = op.map("procesar_raw", entrada, procesar_mensaje_raw)

    # 3. Limpiar texto
    limpio = op.map("limpiar_texto", raw, limpiar_texto)

    # 4. Guardar texto limpio y continuar con el original
    limpio_guardado = op.map("guardar_texto_limpio", limpio, guardar_texto_limpio)

    # 5. Dividir en chunks (un texto genera múltiples chunks)
    chunks = op.flat_map("dividir_chunks", limpio_guardado, dividir_en_chunks)

    # 6. Generar embeddings
    embeddings = op.map("generar_embeddings", chunks, generar_embeddings)

    # 7. Guardar embeddings
    op.sink("guardar_embeddings", embeddings, guardar_embedding)

    return flow


def ejecutar_flujo():
    """Ejecuta el flujo de procesamiento con ByteWax."""
    flow = crear_flujo_bytewax()
    run_main(flow)


if __name__ == "__main__":
    ejecutar_flujo()
