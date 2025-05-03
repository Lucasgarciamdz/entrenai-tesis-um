"""
Definición del flujo de procesamiento con Bytewax
"""

from typing import Dict, List, Any, Optional
import threading
import time
from datetime import datetime

from loguru import logger
from bytewax.dataflow import Dataflow
from bytewax.execution import run_main
from bytewax.operators import map, filter_map

from app.config.configuracion import configuracion
from app.database.conector_rabbitmq import ConectorRabbitMQ
from app.database.conector_qdrant import ConectorQdrant
from app.procesamiento_bytewax.utils import (
    limpiar_texto,
    dividir_en_trunks,
    convertir_a_markdown,
    generar_contexto,
    generar_embedding,
)
from app.procesamiento_bytewax.dispatchers import (
    ProcesoRabbitMQEntradaDispatcher,
    ProcesoQdrantSalidaDispatcher,
)


class FlujoProcesamientoArchivos:
    """
    Define y ejecuta un flujo de procesamiento de datos utilizando Bytewax.

    Este flujo:
    1. Recibe mensajes de RabbitMQ con datos de cambios de MongoDB
    2. Procesa los mensajes filtrando y extrayendo información relevante
    3. Limpia y formatea el texto
    4. Divide el texto en chunks
    5. Genera embeddings para cada chunk
    6. Almacena los embeddings en Qdrant
    """

    def __init__(self, nombre_flujo: str = "flujo_procesamiento"):
        """
        Inicializa el flujo de procesamiento.

        Args:
            nombre_flujo: Nombre identificativo del flujo
        """
        self.nombre_flujo = nombre_flujo
        self.dataflow = Dataflow(nombre_flujo)
        self.configurado = False
        self.ejecutando = False
        self.hilo_ejecucion = None

        # Conexiones
        self.qdrant = None
        self.rabbitmq = None

        # Configuración
        self.cola_entrada = configuracion.obtener_rabbitmq_cola_cambios()
        self.usar_ollama = (
            configuracion.obtener("USAR_OLLAMA", "false").lower() == "true"
        )
        self.modelo_embedding = configuracion.obtener(
            "MODELO_EMBEDDING", "all-MiniLM-L6-v2"
        )
        self.limite_tam_texto = int(
            configuracion.obtener("LIMITE_TAMAÑO_TEXTO", "8192")
        )

        # Estadísticas
        self.mensajes_procesados = 0
        self.embeddings_generados = 0
        self.errores = 0

        logger.info(f"Inicializado flujo '{nombre_flujo}'")
        logger.info(
            f"Configurado para usar {'OLLAMA' if self.usar_ollama else 'sentence-transformers'}"
        )
        logger.info(f"Modelo de embedding: {self.modelo_embedding}")

    def configurar(self) -> bool:
        """
        Configura el flujo de procesamiento con los operadores necesarios.

        Returns:
            True si la configuración es exitosa, False en caso contrario
        """
        try:
            logger.info(f"Configurando flujo '{self.nombre_flujo}'...")

            # Inicializar conexiones si es necesario
            if not self._inicializar_conexiones():
                logger.error("No se pudieron inicializar las conexiones, abortando")
                return False

            # 1. Iniciar con entrada desde RabbitMQ
            entrada = ProcesoRabbitMQEntradaDispatcher(self.rabbitmq, self.cola_entrada)
            self.dataflow.input("entrada", entrada)

            # 2. Filtrar mensajes para obtener solo los que nos interesan
            def filtrar_documento(mensaje: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                try:
                    tipo_operacion = mensaje.get("operationType")
                    # Solo procesar inserts, updates o replaces con documento completo
                    if (
                        tipo_operacion in ["insert", "update", "replace"]
                        and "fullDocument" in mensaje
                    ):
                        documento = mensaje.get("fullDocument", {})
                        # Verificar que tiene texto
                        if documento and "texto" in documento and documento["texto"]:
                            return documento
                    return None
                except Exception as e:
                    logger.error(f"Error al filtrar documento: {e}")
                    return None

            self.dataflow.map(filter_map(filtrar_documento))

            # 3. Extraer información relevante
            def extraer_info(documento: Dict[str, Any]) -> Dict[str, Any]:
                try:
                    # Extraer campos necesarios
                    id_doc = str(documento.get("_id", ""))
                    texto_original = documento.get("texto", "")

                    # Limitar tamaño del texto si es muy grande
                    if len(texto_original) > self.limite_tam_texto:
                        texto = texto_original[: self.limite_tam_texto]
                        logger.warning(
                            f"Texto truncado para documento {id_doc} (de {len(texto_original)} a {len(texto)} caracteres)"
                        )
                    else:
                        texto = texto_original

                    # Preparar metadatos
                    metadatos = {
                        "id_original": id_doc,
                        "tipo_archivo": documento.get("tipo_archivo", "txt"),
                        "nombre_archivo": documento.get(
                            "nombre_archivo", "documento.txt"
                        ),
                        "id_curso": documento.get("id_curso", ""),
                        "nombre_curso": documento.get("nombre_curso", ""),
                        "ruta_archivo": documento.get("ruta_archivo", ""),
                        "fecha_procesamiento": datetime.now().isoformat(),
                    }

                    # Si hay metadatos extras en el documento, incluirlos
                    metadatos_doc = documento.get("metadatos", {})
                    if isinstance(metadatos_doc, dict):
                        for k, v in metadatos_doc.items():
                            # Solo añadir si es string, número o booleano
                            if isinstance(v, (str, int, float, bool)):
                                metadatos[k] = v

                    return {"id": id_doc, "texto": texto, "metadatos": metadatos}
                except Exception as e:
                    logger.error(f"Error al extraer información: {e}")
                    # Devolver datos mínimos para mantener el flujo, pero señalando error
                    id_doc = str(documento.get("_id", "desconocido"))
                    return {
                        "id": id_doc,
                        "texto": "",
                        "metadatos": {"error": str(e), "id_original": id_doc},
                    }

            self.dataflow.map(map(extraer_info))

            # 4. Limpiar y dar formato al texto
            def limpiar_y_formatear(datos: Dict[str, Any]) -> Dict[str, Any]:
                try:
                    id_doc = datos.get("id", "")
                    texto = datos.get("texto", "")

                    if not texto:
                        logger.warning(
                            f"Texto vacío para documento {id_doc}, omitiendo limpieza"
                        )
                        return datos

                    # Limpiar texto
                    texto_limpio = limpiar_texto(texto)

                    # Convertir a markdown para mejor estructura
                    texto_markdown = convertir_a_markdown(texto_limpio)

                    # Actualizar datos con texto limpio
                    datos["texto_original"] = texto
                    datos["texto"] = texto_markdown

                    # Guardar texto limpio en Qdrant
                    if self.qdrant:
                        logger.debug(
                            f"Guardando texto limpio en Qdrant para documento {id_doc}"
                        )
                        self.qdrant.guardar_texto_limpio(
                            id_doc, texto_markdown, datos.get("metadatos", {})
                        )

                    return datos
                except Exception as e:
                    logger.error(f"Error al limpiar texto: {e}")
                    # Mantener datos originales
                    return datos

            self.dataflow.map(map(limpiar_y_formatear))

            # 5. Generar chunks
            def generar_chunks(datos: Dict[str, Any]) -> List[Dict[str, Any]]:
                try:
                    id_doc = datos.get("id", "")
                    texto = datos.get("texto", "")

                    if not texto:
                        logger.warning(
                            f"Texto vacío para documento {id_doc}, omitiendo chunking"
                        )
                        return []

                    # Dividir texto en chunks
                    chunks = dividir_en_trunks(texto)
                    logger.info(f"Documento {id_doc} dividido en {len(chunks)} chunks")

                    # Crear lista de documentos (uno por chunk)
                    resultado = []
                    for i, chunk in enumerate(chunks):
                        # Crear copia de los metadatos
                        metadatos_chunk = datos.get("metadatos", {}).copy()
                        # Añadir información del chunk
                        metadatos_chunk["indice_chunk"] = i
                        metadatos_chunk["total_chunks"] = len(chunks)
                        metadatos_chunk["contexto"] = generar_contexto(chunk)

                        # Crear documento para el chunk
                        doc_chunk = {
                            "id": f"{id_doc}_chunk_{i}",
                            "id_original": id_doc,
                            "texto": chunk,
                            "metadatos": metadatos_chunk,
                        }
                        resultado.append(doc_chunk)

                    self.mensajes_procesados += 1
                    return resultado
                except Exception as e:
                    logger.error(f"Error al generar chunks: {e}")
                    self.errores += 1
                    return []

            # Convertir cada documento en una lista de chunks y aplanar
            self.dataflow.flat_map(map(generar_chunks))

            # 6. Generar embeddings
            def generar_embedding_para_chunk(
                chunk: Dict[str, Any],
            ) -> Optional[Dict[str, Any]]:
                try:
                    id_chunk = chunk.get("id", "")
                    texto = chunk.get("texto", "")

                    if not texto:
                        logger.warning(
                            f"Texto vacío para chunk {id_chunk}, omitiendo embedding"
                        )
                        return None

                    # Generar embedding
                    logger.debug(f"Generando embedding para chunk {id_chunk}")
                    embedding = generar_embedding(
                        texto=texto,
                        modelo_nombre=self.modelo_embedding,
                        usar_ollama=self.usar_ollama,
                    )

                    if not embedding:
                        logger.error(
                            f"No se pudo generar embedding para chunk {id_chunk}"
                        )
                        self.errores += 1
                        return None

                    # Añadir embedding al documento
                    chunk["embedding"] = embedding
                    self.embeddings_generados += 1
                    return chunk

                except Exception as e:
                    logger.error(f"Error al generar embedding: {e}")
                    self.errores += 1
                    return None

            self.dataflow.map(filter_map(generar_embedding_para_chunk))

            # 7. Preparar salida para Qdrant (determinar colección según metadatos)
            def preparar_salida_qdrant(chunk: Dict[str, Any]) -> Dict[str, Any]:
                try:
                    metadatos = chunk.get("metadatos", {})
                    id_curso = metadatos.get("id_curso")

                    # Determinar nombre de colección
                    if id_curso:
                        coleccion = f"curso_{id_curso}"
                    else:
                        coleccion = "general"

                    # Añadir colección al documento
                    chunk["coleccion"] = coleccion
                    return chunk
                except Exception as e:
                    logger.error(f"Error al preparar salida para Qdrant: {e}")
                    # Usar colección por defecto
                    chunk["coleccion"] = "general"
                    return chunk

            self.dataflow.map(map(preparar_salida_qdrant))

            # 8. Configurar salida a Qdrant
            salida = ProcesoQdrantSalidaDispatcher(self.qdrant)
            self.dataflow.output("salida", salida)

            self.configurado = True
            logger.info(f"Flujo '{self.nombre_flujo}' configurado correctamente")
            return True

        except Exception as e:
            logger.error(f"Error al configurar flujo: {e}")
            self.configurado = False
            return False

    def ejecutar(self) -> bool:
        """
        Ejecuta el flujo de procesamiento en un hilo separado.

        Returns:
            True si el flujo inicia correctamente, False en caso contrario
        """
        if not self.configurado:
            logger.error(
                "El flujo no está configurado. Llame a 'configurar()' primero."
            )
            return False

        if self.ejecutando:
            logger.warning("El flujo ya está en ejecución")
            return True

        try:
            logger.info(f"Iniciando flujo '{self.nombre_flujo}'...")

            # Ejecutar en un hilo separado
            self.hilo_ejecucion = threading.Thread(
                target=self._ejecutar_flujo, daemon=True
            )
            self.hilo_ejecucion.start()

            # Esperar a que el flujo esté listo
            tiempo_espera = 2  # segundos
            time.sleep(tiempo_espera)

            if self.hilo_ejecucion.is_alive():
                self.ejecutando = True
                logger.info(f"Flujo '{self.nombre_flujo}' iniciado correctamente")
                return True
            else:
                logger.error("El flujo no pudo iniciarse correctamente")
                return False

        except Exception as e:
            logger.error(f"Error al iniciar flujo: {e}")
            self.ejecutando = False
            return False

    def detener(self) -> bool:
        """
        Detiene la ejecución del flujo de procesamiento.

        Returns:
            True si el flujo se detiene correctamente, False en caso contrario
        """
        if not self.ejecutando:
            logger.warning("El flujo no está en ejecución")
            return True

        try:
            logger.info(f"Deteniendo flujo '{self.nombre_flujo}'...")

            # Cambiar estado para que el hilo sepa que debe detenerse
            self.ejecutando = False

            # Esperar a que el hilo termine
            if self.hilo_ejecucion:
                self.hilo_ejecucion.join(timeout=5)

            logger.info(f"Flujo '{self.nombre_flujo}' detenido correctamente")
            logger.info("Estadísticas finales:")
            logger.info(f"  - Mensajes procesados: {self.mensajes_procesados}")
            logger.info(f"  - Embeddings generados: {self.embeddings_generados}")
            logger.info(f"  - Errores: {self.errores}")

            return True

        except Exception as e:
            logger.error(f"Error al detener flujo: {e}")
            return False

    def _inicializar_conexiones(self) -> bool:
        """
        Inicializa las conexiones necesarias para el flujo.

        Returns:
            True si las conexiones se establecen correctamente, False en caso contrario
        """
        try:
            logger.info("Inicializando conexiones para el flujo...")

            # Conexión a RabbitMQ
            self.rabbitmq = ConectorRabbitMQ()
            if not self.rabbitmq.conectar():
                logger.error("No se pudo conectar a RabbitMQ")
                return False

            # Declarar cola para mensajes
            self.rabbitmq.declarar_cola(self.cola_entrada)
            logger.info(f"Conectado a RabbitMQ y cola '{self.cola_entrada}' declarada")

            # Conexión a Qdrant
            self.qdrant = ConectorQdrant()
            if not self.qdrant.conectar():
                logger.error("No se pudo conectar a Qdrant")
                return False

            logger.info("Conexión a Qdrant establecida")

            return True

        except Exception as e:
            logger.error(f"Error al inicializar conexiones: {e}")
            return False

    def _ejecutar_flujo(self):
        """Método interno para ejecutar el flujo en un hilo separado."""
        try:
            logger.info(f"Ejecutando flujo '{self.nombre_flujo}' en hilo separado")

            # Ejecutar el flujo principal de Bytewax
            run_main(self.dataflow)

        except Exception as e:
            logger.error(f"Error durante la ejecución del flujo: {e}")
        finally:
            logger.info(f"Finalizando ejecución del flujo '{self.nombre_flujo}'")
            self.ejecutando = False
