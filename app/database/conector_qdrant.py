"""
Conector para interactuar con Qdrant.

Este módulo define la clase ConectorQdrant que proporciona
funcionalidad para almacenar y consultar embeddings en Qdrant.
"""

from typing import Dict, List, Any
import time
import uuid

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.models import Distance, VectorParams, PointStruct

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
        usar_https: bool = None,
        api_key: str = None,
    ):
        """
        Inicializa el conector de Qdrant.

        Args:
            host: Host de Qdrant
            puerto: Puerto de Qdrant
            usar_https: Si se debe usar HTTPS
            api_key: Clave API para autenticación
        """
        # Inicializar solo una vez
        if hasattr(self, "inicializado") and self.inicializado:
            return

        # Obtener configuración desde variables
        self.host = host or configuracion.obtener_qdrant_host()
        self.puerto = puerto or configuracion.obtener_qdrant_puerto()
        self.usar_https = (
            usar_https
            if usar_https is not None
            else configuracion.obtener_qdrant_usar_https()
        )
        self.api_key = api_key or configuracion.obtener_qdrant_api_key()

        # Construir URL base para logs
        esquema = "https" if self.usar_https else "http"
        self.url_base = f"{esquema}://{self.host}:{self.puerto}"

        # Inicializar variables de estado
        self.cliente = None
        self.conectado = False
        self.ultima_conexion = None
        self.coleccion_default = configuracion.obtener(
            "QDRANT_COLECCION_DEFAULT", "documentos"
        )
        self.coleccion_textos = configuracion.obtener(
            "QDRANT_COLECCION_TEXTOS", "textos_limpios"
        )
        self.dimension_embeddings = int(
            configuracion.obtener("QDRANT_DIMENSION_EMBEDDINGS", "384")
        )

        # Cache de colecciones verificadas
        self.colecciones_existentes = set()

        logger.info(f"Conector Qdrant inicializado ({self.url_base})")
        self.inicializado = True

    def conectar(self) -> bool:
        """
        Establece conexión con Qdrant.

        Returns:
            True si la conexión es exitosa, False en caso contrario
        """
        try:
            # Usar la biblioteca oficial de Qdrant
            if self.usar_https:
                url = f"https://{self.host}:{self.puerto}"
            else:
                url = f"http://{self.host}:{self.puerto}"

            # Configurar cliente de Qdrant
            headers = {}
            if self.api_key:
                headers["api-key"] = self.api_key

            self.cliente = QdrantClient(
                url=url,
                timeout=5.0,  # 5 segundos de timeout por defecto
                headers=headers,
            )

            # Verificar la conexión consultando la información del servidor
            self.cliente.get_version()

            self.conectado = True
            self.ultima_conexion = time.time()
            logger.debug(f"Conexión con Qdrant establecida ({self.url_base})")

            # Cargar colecciones existentes
            self._cargar_colecciones_existentes()
            return True

        except Exception as e:
            logger.error(f"Error al conectar con Qdrant: {e}")
            self.cliente = None
            self.conectado = False
            return False

    def _cargar_colecciones_existentes(self):
        """Carga la lista de colecciones existentes en Qdrant."""
        try:
            colecciones = self.listar_colecciones()
            self.colecciones_existentes = set()

            for coleccion in colecciones:
                nombre = coleccion.get("nombre")
                if nombre:
                    self.colecciones_existentes.add(nombre)

            logger.info(f"Colecciones en Qdrant: {len(self.colecciones_existentes)}")
            logger.debug(
                f"Colecciones disponibles: {list(self.colecciones_existentes)}"
            )
        except Exception as e:
            logger.error(f"Error al cargar colecciones existentes: {e}")

    def desconectar(self):
        """Desconecta del servidor de Qdrant."""
        if self.cliente:
            # No hay método explícito para cerrar la conexión en QdrantClient
            # pero podemos eliminar la referencia
            self.cliente = None

        self.conectado = False
        self.ultima_conexion = None
        logger.debug("Conexión con Qdrant cerrada")

    def esta_conectado(self) -> bool:
        """
        Verifica si la conexión está activa.

        Returns:
            True si la conexión está activa, False en caso contrario
        """
        # Si hace más de 60 segundos que no verificamos, hacerlo de nuevo
        if (
            not self.conectado
            or not self.ultima_conexion
            or time.time() - self.ultima_conexion > 60
        ):
            return self.conectar()

        return self.conectado

    def listar_colecciones(self) -> List[Dict[str, Any]]:
        """
        Lista las colecciones disponibles en Qdrant.

        Returns:
            Lista de colecciones con sus propiedades
        """
        try:
            if not self.esta_conectado():
                return []

            # Obtener lista de colecciones con la biblioteca oficial
            colecciones = self.cliente.get_collections().collections
            resultado = []

            # Procesar resultados
            for coleccion in colecciones:
                try:
                    # Obtener información detallada de la colección
                    info_coleccion = self.cliente.get_collection(
                        collection_name=coleccion.name
                    )

                    # Determinar tamaño de vector
                    vector_size = 0
                    if hasattr(info_coleccion, "config") and hasattr(
                        info_coleccion.config, "params"
                    ):
                        if hasattr(info_coleccion.config.params, "vectors"):
                            vector_configs = info_coleccion.config.params.vectors
                            # Si es dict, tomar el primer vector config
                            if (
                                isinstance(vector_configs, dict)
                                and len(vector_configs) > 0
                            ):
                                first_config = next(iter(vector_configs.values()))
                                vector_size = first_config.size
                            # Si no es dict, asumir un solo vector config
                            elif hasattr(vector_configs, "size"):
                                vector_size = vector_configs.size

                    resultado.append(
                        {
                            "nombre": coleccion.name,
                            "puntos": getattr(info_coleccion, "vectors_count", 0),
                            "dimension": vector_size,
                        }
                    )
                except Exception as e:
                    logger.warning(
                        f"Error al obtener detalles de colección {coleccion.name}: {e}"
                    )
                    resultado.append(
                        {
                            "nombre": coleccion.name,
                            "puntos": 0,
                            "dimension": self.dimension_embeddings,
                        }
                    )

            return resultado

        except Exception as e:
            logger.error(f"Error al listar colecciones: {e}")
            return []

    def crear_coleccion(
        self, nombre: str, dimension: int = None, descripcion: str = None
    ) -> bool:
        """
        Crea una nueva colección en Qdrant.

        Args:
            nombre: Nombre de la colección
            dimension: Dimensión de los vectores (por defecto, la configurada)
            descripcion: Descripción de la colección

        Returns:
            True si la creación es exitosa, False en caso contrario
        """
        try:
            if not self.esta_conectado():
                return False

            # Verificar si la colección ya existe
            if nombre in self.colecciones_existentes or self.cliente.collection_exists(
                nombre
            ):
                logger.info(f"La colección '{nombre}' ya existe")
                self.colecciones_existentes.add(nombre)
                return True

            dimension = dimension or self.dimension_embeddings

            # Crear colección con la biblioteca oficial
            self.cliente.create_collection(
                collection_name=nombre,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
                hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100)
                if descripcion
                else None,
                metadata={"description": descripcion} if descripcion else None,
            )

            logger.info(f"Colección '{nombre}' creada correctamente")
            self.colecciones_existentes.add(nombre)
            return True

        except Exception as e:
            logger.error(f"Error al crear colección '{nombre}': {e}")
            return False

    def eliminar_coleccion(self, nombre: str) -> bool:
        """
        Elimina una colección de Qdrant.

        Args:
            nombre: Nombre de la colección

        Returns:
            True si la eliminación es exitosa, False en caso contrario
        """
        try:
            if not self.esta_conectado():
                return False

            # Eliminar colección con la biblioteca oficial
            self.cliente.delete_collection(collection_name=nombre)

            logger.info(f"Colección '{nombre}' eliminada correctamente")
            if nombre in self.colecciones_existentes:
                self.colecciones_existentes.remove(nombre)
            return True

        except Exception as e:
            logger.error(f"Error al eliminar colección '{nombre}': {e}")
            return False

    def limpiar_coleccion(self, nombre: str) -> bool:
        """
        Elimina todos los puntos de una colección sin eliminarla.

        Args:
            nombre: Nombre de la colección

        Returns:
            True si la limpieza es exitosa, False en caso contrario
        """
        try:
            if not self.esta_conectado():
                return False

            # Eliminar todos los puntos de la colección
            # En la biblioteca oficial, se puede usar delete_points con un filtro vacío
            self.cliente.delete_points(
                collection_name=nombre,
                points_selector=models.FilterSelector(
                    filter=models.Filter()  # Filtro vacío = todos los puntos
                ),
            )

            logger.info(f"Colección '{nombre}' limpiada correctamente")
            return True

        except Exception as e:
            logger.error(f"Error al limpiar colección '{nombre}': {e}")
            return False

    def guardar_texto_limpio(
        self, id_texto: str, texto: str, metadatos: Dict[str, Any]
    ) -> bool:
        """
        Guarda un texto limpio en Qdrant.

        Args:
            id_texto: ID del texto
            texto: Texto limpio
            metadatos: Metadatos del texto

        Returns:
            True si la operación es exitosa, False en caso contrario
        """
        try:
            if not self.esta_conectado():
                return False

            # Asegurar que existe la colección de textos
            if self.coleccion_textos not in self.colecciones_existentes:
                if not self.crear_coleccion(
                    nombre=self.coleccion_textos,
                    dimension=1,  # Dimensión ficticia, no usaremos vectores
                    descripcion="Colección para textos limpios sin embeddings",
                ):
                    logger.error(
                        f"No se pudo crear la colección '{self.coleccion_textos}'"
                    )
                    return False

            # Convertir id_texto a un formato compatible con Qdrant
            try:
                # Intentar convertir a entero (solo para IDs numéricos)
                punto_id = int(id_texto)
            except (ValueError, TypeError):
                # Si no es un número, generar un UUID v5 basado en el ID
                punto_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(id_texto)))
                logger.debug(f"ID convertido de '{id_texto}' a UUID: {punto_id}")

            # Guardar con la biblioteca oficial
            payload = {"texto": texto, "id_original": id_texto}

            # Añadir metadatos si existen
            if metadatos:
                for clave, valor in metadatos.items():
                    if isinstance(valor, (str, int, float, bool)) or valor is None:
                        payload[clave] = valor

            # Crear punto y guardarlo
            self.cliente.upsert(
                collection_name=self.coleccion_textos,
                points=[
                    PointStruct(
                        id=punto_id,
                        vector=[0.0],  # Vector ficticio (no lo usaremos para búsqueda)
                        payload=payload,
                    )
                ],
            )

            logger.debug(
                f"Texto limpio guardado correctamente con ID {id_texto} (Qdrant ID: {punto_id})"
            )
            return True

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
        coleccion: str = None,
    ) -> bool:
        """
        Guarda un embedding en Qdrant.

        Args:
            id_embedding: ID del embedding
            texto: Texto correspondiente al embedding
            embedding: Vector de embedding
            texto_original_id: ID del texto original
            metadatos: Metadatos del embedding
            coleccion: Nombre de la colección donde guardar (usa la predeterminada si es None)

        Returns:
            True si la operación es exitosa, False en caso contrario
        """
        try:
            if not self.esta_conectado():
                return False

            # Validar embedding
            if not embedding or len(embedding) < 1:
                logger.error(
                    f"Vector de embedding vacío o inválido para ID {id_embedding}"
                )
                return False

            # Determinar colección
            nombre_coleccion = coleccion or self.coleccion_default

            # Asegurar que existe la colección
            if nombre_coleccion not in self.colecciones_existentes:
                dimension = len(embedding)
                if not self.crear_coleccion(
                    nombre=nombre_coleccion,
                    dimension=dimension,
                    descripcion=f"Colección creada automáticamente con dimensión {dimension}",
                ):
                    logger.error(f"No se pudo crear la colección '{nombre_coleccion}'")
                    return False

            # Convertir id_embedding a un formato compatible con Qdrant
            try:
                # Intentar convertir a entero (solo para IDs numéricos)
                punto_id = int(id_embedding)
            except (ValueError, TypeError):
                # Si no es un número, generar un UUID v5 basado en el ID
                punto_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(id_embedding)))
                logger.debug(f"ID convertido de '{id_embedding}' a UUID: {punto_id}")

            # Preparar payload para Qdrant
            payload = {
                "texto": texto,
                "texto_original_id": texto_original_id,
                "id_original": id_embedding,  # Guardar ID original como metadato
            }

            # Añadir metadatos adicionales
            if metadatos:
                for clave, valor in metadatos.items():
                    # Ignorar valores complejos que no se pueden serializar
                    if isinstance(valor, (str, int, float, bool)) or valor is None:
                        payload[clave] = valor

            # Guardar con la biblioteca oficial
            self.cliente.upsert(
                collection_name=nombre_coleccion,
                points=[PointStruct(id=punto_id, vector=embedding, payload=payload)],
            )

            logger.debug(
                f"Embedding guardado correctamente con ID {id_embedding} (Qdrant ID: {punto_id}) en colección '{nombre_coleccion}'"
            )
            return True

        except Exception as e:
            logger.error(f"Error al guardar embedding: {e}")
            return False

    def buscar_similares(
        self,
        texto: str,
        limite: int = 5,
        umbral: float = 0.7,
        filtro: Dict[str, Any] = None,
        coleccion: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Busca textos similares a un texto dado.

        Args:
            texto: Texto para buscar similares
            limite: Número máximo de resultados
            umbral: Umbral de similitud (0-1)
            filtro: Filtro opcional para la búsqueda
            coleccion: Nombre de la colección donde buscar (usa la predeterminada si es None)

        Returns:
            Lista de documentos similares
        """
        try:
            if not self.esta_conectado():
                return []

            # Importar generador de embeddings
            from app.procesamiento_bytewax.utils import generar_embedding

            # Generar embedding para el texto
            embedding = generar_embedding(texto)

            if not embedding:
                logger.error("No se pudo generar embedding para la búsqueda")
                return []

            # Determinar colección
            nombre_coleccion = coleccion or self.coleccion_default

            # Verificar que existe la colección
            if nombre_coleccion not in self.colecciones_existentes:
                logger.error(f"La colección '{nombre_coleccion}' no existe")
                return []

            # Convertir filtro si está definido
            qdrant_filtro = None
            if filtro:
                # Aquí se debería convertir el filtro al formato de Qdrant
                # Este es un ejemplo simplificado, ajustar según tu estructura de filtros
                condiciones = []
                for clave, valor in filtro.items():
                    if isinstance(valor, dict) and "gte" in valor:
                        condiciones.append(
                            models.FieldCondition(
                                key=clave, range=models.Range(gte=valor["gte"])
                            )
                        )
                    elif isinstance(valor, list):
                        condiciones.append(
                            models.FieldCondition(
                                key=clave, match=models.MatchAny(any=valor)
                            )
                        )
                    else:
                        condiciones.append(
                            models.FieldCondition(
                                key=clave, match=models.MatchValue(value=valor)
                            )
                        )

                if condiciones:
                    qdrant_filtro = models.Filter(must=condiciones)

            # Realizar búsqueda con la biblioteca oficial
            resultados = self.cliente.search(
                collection_name=nombre_coleccion,
                query_vector=embedding,
                limit=limite,
                score_threshold=umbral,
                query_filter=qdrant_filtro,
            )

            # Procesar resultados
            resultado_final = []
            for item in resultados:
                doc = {
                    "id": item.id,
                    "score": item.score,
                    "texto": item.payload.get("texto", ""),
                }

                # Añadir otros campos del payload
                for clave, valor in item.payload.items():
                    if clave != "texto":
                        doc[clave] = valor

                resultado_final.append(doc)

            return resultado_final

        except Exception as e:
            logger.error(f"Error al buscar textos similares: {e}")
            return []


# Crear una instancia global
conector_qdrant = ConectorQdrant()
