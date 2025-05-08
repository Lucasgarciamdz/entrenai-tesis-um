"""
Conector para interactuar con Qdrant.

Este módulo define la clase ConectorQdrant que proporciona
funcionalidad para almacenar y consultar embeddings en Qdrant.
"""

import uuid
import time
from typing import Dict, List, Any, Optional

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import CollectionStatus

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
        # Obtener prefijo de colección una vez
        self.collection_prefix = configuracion.obtener(
            "QDRANT_COLLECTION_PREFIX", "curso_"
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
                timeout=5,  # Timeout debe ser int o None
                headers=headers,
            )

            # Verificar la conexión intentando listar colecciones
            try:
                self.cliente.get_collections()
                self.conectado = True
                self.ultima_conexion = time.time()
                logger.debug(f"Conexión con Qdrant establecida ({self.url_base})")

                # Cargar colecciones existentes
                self._cargar_colecciones_existentes()
                return True

            except UnexpectedResponse as e:
                if e.status_code == 401:  # Error de autenticación
                    logger.error(
                        "Error de autenticación en Qdrant. Verifique las credenciales."
                    )
                    return False
                raise  # Re-lanzar otros errores inesperados

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
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.warning("No conectado a Qdrant para listar colecciones.")
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

                    # Obtener recuento de puntos de forma segura
                    puntos = None
                    try:
                        if hasattr(info_coleccion, "vectors_count"):
                            puntos = info_coleccion.vectors_count
                        elif (
                            hasattr(info_coleccion, "status") and info_coleccion.status
                        ):
                            # En versiones más recientes puede estar en status
                            puntos = getattr(
                                info_coleccion.status, "vectors_count", None
                            )

                        # Si puntos es None, intentar verificar manualmente
                        if puntos is None:
                            # Intentar obtener al menos un punto para verificar si hay datos
                            try:
                                scroll_result = self.cliente.scroll(
                                    collection_name=coleccion.name,
                                    limit=1,
                                    with_payload=False,
                                    with_vectors=False,
                                )
                                # Si hay resultados, indicar al menos 1 punto
                                if scroll_result and len(scroll_result[0]) > 0:
                                    puntos = len(scroll_result[0])
                                    logger.debug(
                                        f"Colección {coleccion.name} tiene al menos {puntos} puntos (verificado manualmente)"
                                    )
                                else:
                                    puntos = 0
                            except Exception as e:
                                logger.warning(
                                    f"Error al verificar puntos manualmente en {coleccion.name}: {e}"
                                )
                                puntos = 0
                    except (AttributeError, TypeError) as e:
                        logger.warning(
                            f"Error al obtener recuento de puntos para {coleccion.name}: {e}"
                        )
                        puntos = 0

                    resultado.append(
                        {
                            "nombre": coleccion.name,
                            "puntos": puntos,
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
                            "puntos": None,
                            "dimension": self.dimension_embeddings,
                        }
                    )

            return resultado

        except Exception as e:
            logger.error(f"Error al listar colecciones: {e}")
            return []

    def coleccion_tiene_puntos(self, nombre_coleccion: str) -> bool:
        """
        Verifica si una colección tiene puntos almacenados.

        Args:
            nombre_coleccion: Nombre de la colección a verificar

        Returns:
            True si la colección existe y tiene puntos, False en caso contrario
        """
        try:
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.warning(
                    f"No conectado a Qdrant para verificar puntos en {nombre_coleccion}."
                )
                return False

            # Verificar si la colección existe
            if not self.cliente.collection_exists(nombre_coleccion):
                return False

            # Obtener información de la colección
            info_coleccion = self.cliente.get_collection(
                collection_name=nombre_coleccion
            )

            # Intentar obtener recuento de puntos
            puntos = None
            try:
                if hasattr(info_coleccion, "vectors_count"):
                    puntos = info_coleccion.vectors_count
                elif hasattr(info_coleccion, "status") and info_coleccion.status:
                    puntos = getattr(info_coleccion.status, "vectors_count", None)
            except (AttributeError, TypeError):
                pass

            # Si pudimos obtener el recuento de puntos, verificar si es mayor a 0
            if puntos is not None:
                return puntos > 0

            # Si no pudimos obtener el recuento, intentar obtener algunos puntos manualmente
            try:
                # Intentar hacer una búsqueda simple para ver si hay puntos
                resultado = self.cliente.scroll(
                    collection_name=nombre_coleccion,
                    limit=1,  # Solo necesitamos uno para saber si hay puntos
                    with_payload=False,  # No necesitamos los metadatos
                    with_vectors=False,  # No necesitamos los vectores
                )

                # Si hay al menos un punto, resultado[0] tendrá al menos un elemento
                return len(resultado[0]) > 0
            except Exception as e:
                logger.warning(
                    f"Error al verificar puntos manualmente en {nombre_coleccion}: {e}"
                )
                return False

        except Exception as e:
            logger.error(
                f"Error al verificar si la colección {nombre_coleccion} tiene puntos: {e}"
            )
            return False

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
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.error("No conectado a Qdrant para crear colección.")
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
                vectors_config=models.VectorParams(
                    size=dimension, distance=models.Distance.COSINE
                ),
                hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
                optimizers_config=models.OptimizersConfigDiff(
                    default_segment_number=2, memmap_threshold=20000
                ),
                # El parámetro 'metadata' no es válido en create_collection.
                # La descripción u otros metadatos de la colección no se pueden
                # establecer directamente a través de este método en versiones recientes.
            )

            # Esperar a que la colección esté lista
            status = self.cliente.get_collection(nombre).status
            if status != CollectionStatus.GREEN:
                logger.warning(
                    f"La colección '{nombre}' se creó pero su estado es {status}"
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
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.error("No conectado a Qdrant para eliminar colección.")
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
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.error("No conectado a Qdrant para limpiar colección.")
                return False

            # Eliminar todos los puntos de la colección
            self.cliente.delete(
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
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.error("No conectado a Qdrant para guardar texto limpio.")
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
                    models.PointStruct(
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
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.error("No conectado a Qdrant para guardar embedding.")
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
                points=[
                    models.PointStruct(id=punto_id, vector=embedding, payload=payload)
                ],
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
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.warning("No conectado a Qdrant para buscar similares.")
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

    def buscar_por_id_original(
        self, coleccion: str, id_original: str
    ) -> List[Dict[str, Any]]:
        """
        Busca puntos por su ID original en una colección.

        Args:
            coleccion: Nombre de la colección donde buscar
            id_original: ID original del documento

        Returns:
            Lista de puntos encontrados
        """
        try:
            if (
                not self.esta_conectado() or not self.cliente
            ):  # Asegurar que el cliente existe
                logger.warning("No conectado a Qdrant para buscar por ID original.")
                return []

            # Crear filtro para buscar por id_original
            filtro = models.Filter(
                must=[
                    models.FieldCondition(
                        key="id_original",
                        match=models.MatchValue(value=str(id_original)),
                    )
                ]
            )

            # Realizar búsqueda
            resultados = self.cliente.scroll(
                collection_name=coleccion,
                scroll_filter=filtro,
                limit=100,  # Ajustar según necesidad
            )[0]  # scroll retorna (puntos, siguiente_offset)

            # Procesar resultados
            resultado_final = []
            for item in resultados:
                doc = {
                    "id": item.id,
                    "texto": item.payload.get("texto", ""),
                    "metadatos": {},
                }

                # Añadir metadatos del payload
                for clave, valor in item.payload.items():
                    if clave not in ["texto"]:
                        doc["metadatos"][clave] = valor

                resultado_final.append(doc)

            return resultado_final

        except Exception as e:
            logger.error(f"Error al buscar por ID original: {e}")
            return []

    def asegurar_coleccion_curso(
        self, course_id: int, course_name_slug: Optional[str] = None
    ) -> Optional[str]:
        """
        Asegura que la colección para un curso específico exista.
        La crea si no existe.

        Args:
            course_id: ID del curso.
            course_name_slug: Slug del nombre del curso (opcional).

        Returns:
            El nombre de la colección si se pudo crear o ya existía, None en caso de error.
        """
        try:
            # Usar configuración para el prefijo
            prefijo = self.collection_prefix  # Usar el atributo de clase

            # Construir nombre de la colección
            if course_name_slug:
                # Limitar longitud del slug si es necesario
                max_slug_len = 50  # Ajustar si es necesario
                safe_slug = course_name_slug[:max_slug_len]
                nombre_coleccion = f"{prefijo}{course_id}_{safe_slug}"
            else:
                nombre_coleccion = f"{prefijo}{course_id}"

            dimension = int(configuracion.obtener("QDRANT_DIMENSION_EMBEDDINGS", "384"))

            if self.crear_coleccion(nombre=nombre_coleccion, dimension=dimension):
                # crear_coleccion devuelve True si se creó o ya existía
                return nombre_coleccion
            else:
                # Si crear_coleccion devuelve False, hubo un error en la creación
                # (y no fue porque ya existía, ya que ese caso devuelve True)
                logger.error(
                    f"No se pudo asegurar la existencia de la colección '{nombre_coleccion}'"
                )
                return None
        except Exception as e:
            logger.error(
                f"Error inesperado al asegurar colección para curso {course_id}: {e}"
            )
            return None


# Crear una instancia global
conector_qdrant = ConectorQdrant()
