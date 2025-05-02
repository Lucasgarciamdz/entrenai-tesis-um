"""
Conector para interactuar con Qdrant.

Este módulo define la clase ConectorQdrant que proporciona
funcionalidad para almacenar y consultar embeddings en Qdrant.
"""

from typing import Dict, List, Any

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models

from ..config.configuracion import configuracion


class ConectorQdrant:
    """
    Conector para interactuar con Qdrant.

    Esta clase implementa el patrón singleton para mantener una única
    conexión con Qdrant, proporcionando métodos para guardar y consultar
    embeddings en la base de datos vectorial.
    """

    _instancia = None

    def __new__(cls, *args, **kwargs):
        """Implementación del patrón singleton."""
        if cls._instancia is None:
            cls._instancia = super(ConectorQdrant, cls).__new__(cls)
        return cls._instancia

    def __init__(
        self,
        host: str = None,
        puerto: int = None,
        coleccion_texto: str = "texto_limpio",
        coleccion_embeddings: str = "embeddings",
    ):
        """
        Inicializa el conector de Qdrant.

        Args:
            host: Host de Qdrant
            puerto: Puerto de Qdrant
            coleccion_texto: Nombre de la colección para texto limpio
            coleccion_embeddings: Nombre de la colección para embeddings
        """
        # Inicializar solo una vez
        if hasattr(self, "inicializado") and self.inicializado:
            return

        # Cargar parámetros desde configuración o valores por defecto
        self.host = host or configuracion.obtener("QDRANT_HOST", "localhost")
        self.puerto = puerto or int(configuracion.obtener("QDRANT_PORT", "6333"))
        self.coleccion_texto = coleccion_texto
        self.coleccion_embeddings = coleccion_embeddings

        # Estado de la conexión
        self.cliente = None
        self.inicializado = True

    def conectar(self) -> bool:
        """
        Establece conexión con Qdrant.

        Returns:
            True si la conexión es exitosa, False en caso contrario
        """
        try:
            self.cliente = QdrantClient(
                host=self.host,
                port=self.puerto,
            )

            # Verificar conexión
            info = self.cliente.get_collections()
            logger.info(f"Conexión exitosa a Qdrant en {self.host}:{self.puerto}")

            # Asegurar que existan las colecciones
            self._asegurar_colecciones()

            return True
        except Exception as e:
            logger.error(f"Error al conectar a Qdrant: {e}")
            self.cliente = None
            return False

    def desconectar(self):
        """Cierra la conexión con Qdrant."""
        self.cliente = None
        logger.info("Conexión a Qdrant cerrada")

    def esta_conectado(self) -> bool:
        """
        Verifica si la conexión con Qdrant está activa.

        Returns:
            True si la conexión está activa, False en caso contrario
        """
        if self.cliente is None:
            return False

        try:
            # Intentar una operación simple para verificar conexión
            self.cliente.get_collections()
            return True
        except Exception:
            return False

    def _asegurar_colecciones(self):
        """Asegura que existan las colecciones necesarias."""
        try:
            # Colección para texto limpio (no vectorial)
            if not self._existe_coleccion(self.coleccion_texto):
                self.cliente.create_collection(
                    collection_name=self.coleccion_texto,
                    vectors_config=None,  # No es vectorial
                )
                logger.info(f"Colección '{self.coleccion_texto}' creada")

            # Colección para embeddings
            if not self._existe_coleccion(self.coleccion_embeddings):
                self.cliente.create_collection(
                    collection_name=self.coleccion_embeddings,
                    vectors_config=models.VectorParams(
                        size=384,  # Tamaño para all-MiniLM-L6-v2
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(f"Colección '{self.coleccion_embeddings}' creada")

                # Crear índice para búsqueda eficiente
                self.cliente.create_payload_index(
                    collection_name=self.coleccion_embeddings,
                    field_name="text_original_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                logger.info(
                    f"Índice creado para colección '{self.coleccion_embeddings}'"
                )

        except Exception as e:
            logger.error(f"Error al asegurar colecciones: {e}")

    def _existe_coleccion(self, nombre_coleccion: str) -> bool:
        """
        Verifica si existe una colección en Qdrant.

        Args:
            nombre_coleccion: Nombre de la colección

        Returns:
            True si la colección existe, False en caso contrario
        """
        try:
            colecciones = self.cliente.get_collections()
            return nombre_coleccion in [c.name for c in colecciones.collections]
        except Exception as e:
            logger.error(
                f"Error al verificar existencia de colección '{nombre_coleccion}': {e}"
            )
            return False

    def guardar_texto_limpio(
        self, id_texto: str, texto: str, metadatos: Dict[str, Any]
    ) -> bool:
        """
        Guarda un texto limpio en Qdrant.

        Args:
            id_texto: ID del texto
            texto: Texto limpio a guardar
            metadatos: Metadatos del texto

        Returns:
            True si la operación es exitosa, False en caso contrario
        """
        if not self.esta_conectado() and not self.conectar():
            return False

        try:
            # Preparar punto para Qdrant
            punto = models.PointStruct(
                id=id_texto,
                payload={"text": texto, **metadatos},
            )

            # Guardar punto
            resultado = self.cliente.upsert(
                collection_name=self.coleccion_texto,
                points=[punto],
            )

            return resultado.status == models.UpdateStatus.COMPLETED
        except Exception as e:
            logger.error(f"Error al guardar texto limpio: {e}")
            return False

    def guardar_embedding(
        self,
        id_embedding: str,
        texto: str,
        embedding: List[float],
        texto_original_id: str,
        metadatos: Dict[str, Any],
    ) -> bool:
        """
        Guarda un embedding en Qdrant.

        Args:
            id_embedding: ID del embedding
            texto: Texto correspondiente al embedding
            embedding: Vector de embedding
            texto_original_id: ID del texto original
            metadatos: Metadatos del embedding

        Returns:
            True si la operación es exitosa, False en caso contrario
        """
        if not self.esta_conectado() and not self.conectar():
            return False

        try:
            # Preparar punto para Qdrant
            punto = models.PointStruct(
                id=id_embedding,
                vector=embedding,
                payload={
                    "text": texto,
                    "text_original_id": texto_original_id,
                    **metadatos,
                },
            )

            # Guardar punto
            resultado = self.cliente.upsert(
                collection_name=self.coleccion_embeddings,
                points=[punto],
            )

            return resultado.status == models.UpdateStatus.COMPLETED
        except Exception as e:
            logger.error(f"Error al guardar embedding: {e}")
            return False

    def eliminar_texto(self, id_texto: str) -> bool:
        """
        Elimina un texto de Qdrant.

        Args:
            id_texto: ID del texto a eliminar

        Returns:
            True si la operación es exitosa, False en caso contrario
        """
        if not self.esta_conectado() and not self.conectar():
            return False

        try:
            # Eliminar texto limpio
            self.cliente.delete(
                collection_name=self.coleccion_texto,
                points_selector=models.PointIdsList(
                    points=[id_texto],
                ),
            )

            # Eliminar embeddings asociados
            self.cliente.delete(
                collection_name=self.coleccion_embeddings,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="text_original_id",
                                match=models.MatchValue(value=id_texto),
                            )
                        ]
                    )
                ),
            )

            return True
        except Exception as e:
            logger.error(f"Error al eliminar texto: {e}")
            return False

    def buscar_similares(
        self,
        texto_consulta: str,
        embedding_consulta: List[float] = None,
        limite: int = 10,
        umbral: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        Busca los textos más similares a una consulta.

        Args:
            texto_consulta: Texto de la consulta
            embedding_consulta: Vector de embedding de la consulta (opcional)
            limite: Número máximo de resultados
            umbral: Umbral mínimo de similitud (0 a 1)

        Returns:
            Lista de resultados ordenados por similitud
        """
        if not self.esta_conectado() and not self.conectar():
            return []

        try:
            # Buscar en la colección de embeddings
            resultados = self.cliente.search(
                collection_name=self.coleccion_embeddings,
                query_vector=embedding_consulta,
                limit=limite,
                score_threshold=umbral,
            )

            # Formatear resultados
            return [
                {
                    "id": r.id,
                    "texto": r.payload.get("text", ""),
                    "contexto": r.payload.get("contexto", ""),
                    "similitud": r.score,
                    "metadatos": {
                        k: v
                        for k, v in r.payload.items()
                        if k not in ["text", "contexto", "text_original_id"]
                    },
                }
                for r in resultados
            ]
        except Exception as e:
            logger.error(f"Error al buscar textos similares: {e}")
            return []

    def crear_coleccion(
        self, nombre: str, descripcion: str = "", dimension: int = 384
    ) -> bool:
        """
        Crea una nueva colección en Qdrant para almacenar embeddings.

        Args:
            nombre: Nombre de la colección
            descripcion: Descripción de la colección
            dimension: Dimensión de los vectores (por defecto 384 para all-MiniLM-L6-v2)

        Returns:
            True si la operación es exitosa, False en caso contrario
        """
        if not self.esta_conectado() and not self.conectar():
            return False

        try:
            # Verificar si la colección ya existe
            if self._existe_coleccion(nombre):
                logger.info(f"La colección '{nombre}' ya existe")
                return True

            # Crear la colección
            self.cliente.create_collection(
                collection_name=nombre,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
                metadata={
                    "description": descripcion,
                },
            )

            logger.info(f"Colección '{nombre}' creada exitosamente")

            # Crear índice para búsqueda eficiente
            self.cliente.create_payload_index(
                collection_name=nombre,
                field_name="text_original_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

            return True
        except Exception as e:
            logger.error(f"Error al crear colección '{nombre}': {e}")
            return False

    def listar_colecciones(self) -> List[Dict[str, Any]]:
        """
        Lista todas las colecciones existentes en Qdrant con información detallada.

        Returns:
            Lista de diccionarios con información de cada colección
        """
        if not self.esta_conectado() and not self.conectar():
            return []

        try:
            # Obtener colecciones
            colecciones = self.cliente.get_collections()

            resultado = []
            for coleccion in colecciones.collections:
                try:
                    # Obtener información detallada de la colección
                    info = self.cliente.get_collection(collection_name=coleccion.name)

                    # Obtener cantidad de puntos
                    count = self.cliente.count(collection_name=coleccion.name)

                    # Añadir a resultados
                    resultado.append(
                        {
                            "nombre": coleccion.name,
                            "vectores": info.config.params.vectors is not None,
                            "dimension": info.config.params.vectors.size
                            if info.config.params.vectors
                            else None,
                            "distancia": info.config.params.vectors.distance
                            if info.config.params.vectors
                            else None,
                            "puntos": count.count,
                            "metadata": info.config.params.metadata,
                        }
                    )
                except Exception as e:
                    # Si falla una colección, continuar con las demás
                    logger.error(
                        f"Error al obtener información de colección '{coleccion.name}': {e}"
                    )
                    resultado.append({"nombre": coleccion.name, "error": str(e)})

            return resultado

        except Exception as e:
            logger.error(f"Error al listar colecciones: {e}")
            return []


# Crear una instancia global
conector_qdrant = ConectorQdrant()
