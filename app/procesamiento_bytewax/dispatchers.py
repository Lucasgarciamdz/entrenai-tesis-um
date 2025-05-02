"""
Dispatchers para el procesamiento de datos con ByteWax.

Este módulo implementa los dispatchers que determinan cómo procesar
cada tipo de dato en la pipeline de ByteWax, utilizando el patrón
de diseño Factory + Strategy.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any

from loguru import logger

from .modelos import ModeloRaw, ModeloLimpio, ModeloTrunk, ModeloEmbedding
from .utils import (
    limpiar_texto,
    convertir_a_markdown,
    dividir_en_trunks,
    generar_contexto,
    generar_embedding,
)


class HandlerBase(ABC):
    """Clase base para todos los handlers."""

    @abstractmethod
    def procesar(self, item: Any) -> Any:
        """
        Procesa un item y devuelve el resultado.

        Args:
            item: Item a procesar

        Returns:
            Resultado procesado
        """
        pass


class HandlerLimpieza(HandlerBase):
    """Handler base para la limpieza de textos."""

    def procesar(self, item: ModeloRaw) -> ModeloLimpio:
        """
        Limpia el texto de un ModeloRaw.

        Args:
            item: ModeloRaw a procesar

        Returns:
            ModeloLimpio con el texto limpio
        """
        texto_limpio = limpiar_texto(item.texto)
        texto_markdown = convertir_a_markdown(texto_limpio)

        return ModeloLimpio(
            id=item.id,
            tipo=item.tipo,
            texto_limpio=texto_markdown,
            metadatos=item.metadatos,
            formato_original=item.metadatos.get("tipo_archivo", "txt"),
        )


class HandlerChunking(HandlerBase):
    """Handler base para el chunking de textos."""

    def procesar(self, item: ModeloLimpio) -> list[ModeloTrunk]:
        """
        Divide el texto de un ModeloLimpio en trunks.

        Args:
            item: ModeloLimpio a procesar

        Returns:
            Lista de ModeloTrunk con los fragmentos del texto
        """
        # Dividir el texto en trunks
        chunks = dividir_en_trunks(item.texto_limpio)

        # Crear un ModeloTrunk para cada chunk
        resultado = []
        for i, chunk in enumerate(chunks):
            # Generar contexto para el chunk
            contexto = generar_contexto(chunk)

            resultado.append(
                ModeloTrunk(
                    id=f"{item.id}_trunk_{i}",
                    tipo=item.tipo,
                    texto=chunk,
                    indice=i,
                    metadatos=item.metadatos,
                    texto_original_id=item.id,
                    contexto=contexto,
                )
            )

        return resultado


class HandlerEmbedding(HandlerBase):
    """Handler base para la generación de embeddings."""

    def procesar(self, item: ModeloTrunk) -> ModeloEmbedding:
        """
        Genera el embedding para un ModeloTrunk.

        Args:
            item: ModeloTrunk a procesar

        Returns:
            ModeloEmbedding con el vector de embedding
        """
        # Generar embedding
        embedding = generar_embedding(item.texto)

        return ModeloEmbedding(
            id=item.id,
            tipo=item.tipo,
            texto=item.texto,
            indice=item.indice,
            metadatos=item.metadatos,
            texto_original_id=item.texto_original_id,
            contexto=item.contexto,
            embedding=embedding,
            modelo_embedding="all-MiniLM-L6-v2",
        )


# Factory para crear handlers de limpieza según el tipo
class LimpiezaHandlerFactory:
    """Factory para crear handlers de limpieza según el tipo de dato."""

    @staticmethod
    def crear_handler(tipo: str) -> HandlerBase:
        """
        Crea un handler de limpieza según el tipo de dato.

        Args:
            tipo: Tipo de dato a procesar (ej: "pdf", "html")

        Returns:
            HandlerLimpieza adecuado para el tipo
        """
        # En una implementación más compleja, aquí se seleccionaría
        # un handler específico según el tipo de documento
        return HandlerLimpieza()


# Factory para crear handlers de chunking según el tipo
class ChunkingHandlerFactory:
    """Factory para crear handlers de chunking según el tipo de dato."""

    @staticmethod
    def crear_handler(tipo: str) -> HandlerBase:
        """
        Crea un handler de chunking según el tipo de dato.

        Args:
            tipo: Tipo de dato a procesar

        Returns:
            HandlerChunking adecuado para el tipo
        """
        # Por ahora usamos el mismo handler para todos los tipos
        return HandlerChunking()


# Factory para crear handlers de embedding según el tipo
class EmbeddingHandlerFactory:
    """Factory para crear handlers de embedding según el tipo de dato."""

    @staticmethod
    def crear_handler(tipo: str) -> HandlerBase:
        """
        Crea un handler de embedding según el tipo de dato.

        Args:
            tipo: Tipo de dato a procesar

        Returns:
            HandlerEmbedding adecuado para el tipo
        """
        # Por ahora usamos el mismo handler para todos los tipos
        return HandlerEmbedding()


# Dispatchers para cada etapa del proceso
class RawDispatcher:
    """Dispatcher para datos crudos."""

    @staticmethod
    def procesar(mensaje: Dict[str, Any]) -> ModeloRaw:
        """
        Procesa un mensaje crudo de RabbitMQ y lo convierte a ModeloRaw.

        Args:
            mensaje: Mensaje recibido de RabbitMQ

        Returns:
            ModeloRaw construido a partir del mensaje
        """
        try:
            # Extraer datos del mensaje
            doc = mensaje.get("documento", {})
            id_doc = mensaje.get("documento_id", "")
            coleccion = mensaje.get("coleccion", "")
            operacion = mensaje.get("operacion", "")

            # Extraer texto y metadatos según el tipo de documento
            texto = ""
            metadatos = {}

            if coleccion == "contenidos":
                texto = doc.get("texto", "")
                metadatos = {
                    "id_curso": doc.get("id_curso", ""),
                    "nombre_curso": doc.get("nombre_curso", ""),
                    "nombre_archivo": doc.get("nombre_archivo", ""),
                    "tipo_archivo": doc.get("tipo_archivo", ""),
                }

                # Agregar metadatos específicos según el tipo
                if "total_paginas" in doc:
                    metadatos["total_paginas"] = doc.get("total_paginas", 0)

                if "procesado_con_ocr" in doc:
                    metadatos["procesado_con_ocr"] = doc.get("procesado_con_ocr", False)

                if "tiene_imagenes" in doc:
                    metadatos["tiene_imagenes"] = doc.get("tiene_imagenes", False)

                tipo = doc.get("tipo_archivo", "txt")
            else:
                # Manejar otros tipos de colecciones si es necesario
                logger.warning(f"Colección no soportada: {coleccion}")
                tipo = "desconocido"

            # Crear y devolver ModeloRaw
            return ModeloRaw(
                id=id_doc,
                tipo=tipo,
                texto=texto,
                metadatos=metadatos,
                coleccion=coleccion,
                operacion=operacion,
            )

        except Exception as e:
            logger.error(f"Error al procesar mensaje crudo: {e}")
            raise


class LimpiezaDispatcher:
    """Dispatcher para la limpieza de textos."""

    @staticmethod
    def procesar(item: ModeloRaw) -> ModeloLimpio:
        """
        Procesa un ModeloRaw y lo convierte a ModeloLimpio.

        Args:
            item: ModeloRaw a procesar

        Returns:
            ModeloLimpio con el texto limpio
        """
        try:
            # Crear handler según el tipo
            handler = LimpiezaHandlerFactory.crear_handler(item.tipo)

            # Procesar item
            return handler.procesar(item)

        except Exception as e:
            logger.error(f"Error en LimpiezaDispatcher: {e}")
            raise


class ChunkingDispatcher:
    """Dispatcher para el chunking de textos."""

    @staticmethod
    def procesar(item: ModeloLimpio) -> list[ModeloTrunk]:
        """
        Procesa un ModeloLimpio y lo convierte a lista de ModeloTrunk.

        Args:
            item: ModeloLimpio a procesar

        Returns:
            Lista de ModeloTrunk con los fragmentos del texto
        """
        try:
            # Crear handler según el tipo
            handler = ChunkingHandlerFactory.crear_handler(item.tipo)

            # Procesar item
            return handler.procesar(item)

        except Exception as e:
            logger.error(f"Error en ChunkingDispatcher: {e}")
            raise


class EmbeddingDispatcher:
    """Dispatcher para la generación de embeddings."""

    @staticmethod
    def procesar(item: ModeloTrunk) -> ModeloEmbedding:
        """
        Procesa un ModeloTrunk y lo convierte a ModeloEmbedding.

        Args:
            item: ModeloTrunk a procesar

        Returns:
            ModeloEmbedding con el vector de embedding
        """
        try:
            # Crear handler según el tipo
            handler = EmbeddingHandlerFactory.crear_handler(item.tipo)

            # Procesar item
            return handler.procesar(item)

        except Exception as e:
            logger.error(f"Error en EmbeddingDispatcher: {e}")
            raise
