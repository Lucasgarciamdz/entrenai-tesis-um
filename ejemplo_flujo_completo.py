#!/usr/bin/env python
"""
Ejemplo de flujo completo de procesamiento de archivos de Moodle.

Este script demuestra el flujo completo desde la descarga de archivos
de Moodle hasta su procesamiento y almacenamiento en la base de datos vectorial.
"""

import sys
import os
import time
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

# Cargar variables de entorno desde .env si existe
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Configurar logging
logger.remove()
logger.add(
    sys.stderr,
    level=os.getenv("NIVEL_LOG", "INFO"),
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)
logger.add(
    "flujo_completo.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="10 MB",
)

from app.database.conector_mongodb import ConectorMongoDB
from app.database.conector_rabbitmq import ConectorRabbitMQ
from app.database.conector_qdrant import ConectorQdrant
from app.database.cdc_mongodb import crear_monitor_cdc
from app.config.configuracion import configuracion
from app.database.modelos_documentos import ContenidoTexto
from app.procesamiento_bytewax.flujo_bytewax import crear_flujo_procesamiento


def crear_ejemplo_documento():
    """
    Crea un documento de ejemplo en MongoDB para probar el flujo.

    Returns:
        Documento creado o None si hay error
    """
    logger.info("Creando documento de ejemplo en MongoDB...")

    # Conectar a MongoDB
    mongodb = ConectorMongoDB(
        host=configuracion.obtener_mongodb_host(),
        puerto=configuracion.obtener_mongodb_puerto(),
        usuario=configuracion.obtener_mongodb_usuario(),
        contraseña=configuracion.obtener_mongodb_contraseña(),
        base_datos=configuracion.obtener_mongodb_base_datos(),
    )

    # Crear documento de texto
    texto_ejemplo = """
# Introducción a Machine Learning

## Conceptos Fundamentales

El aprendizaje automático (Machine Learning) es una rama de la inteligencia artificial que se centra en el desarrollo de técnicas que permiten a las computadoras aprender a partir de datos.

### Tipos de aprendizaje

Hay varios tipos de aprendizaje en Machine Learning:

1. **Aprendizaje supervisado**: El algoritmo aprende de datos etiquetados.
   - Regresión: Predice valores continuos
   - Clasificación: Predice categorías

2. **Aprendizaje no supervisado**: El algoritmo aprende de datos sin etiquetar.
   - Clustering: Agrupa datos similares
   - Reducción de dimensionalidad

3. **Aprendizaje por refuerzo**: El algoritmo aprende mediante prueba y error.

## Algoritmos Comunes

### Regresión Lineal

La fórmula de regresión lineal es:
y = mx + b

Donde:
- y es la variable dependiente
- x es la variable independiente
- m es la pendiente
- b es el intercepto

### Redes Neuronales

Las redes neuronales están inspiradas en el cerebro humano y consisten en capas de neuronas interconectadas.
"""

    # Crear modelo
    documento = ContenidoTexto(
        id_curso=1,
        nombre_curso="Curso de Inteligencia Artificial",
        titulo="Introducción a Machine Learning",
        texto=texto_ejemplo,
        tipo_contenido="markdown",
        metadatos={
            "autor": "Profesor Ejemplo",
            "fecha_creacion": "2023-01-15",
            "tipo_recurso": "material_clase",
            "etiquetas": ["machine learning", "ia", "introducción"],
        },
    )

    # Guardar en MongoDB
    id_documento = mongodb.guardar(documento)
    if id_documento:
        logger.success(f"Documento creado con ID: {id_documento}")
        # Agregar ID al documento para referencia futura
        documento.id = id_documento
        return documento
    else:
        logger.error("Error al crear documento")
        return None


def configurar_monitor_cdc():
    """
    Configura y ejecuta un monitor CDC para procesar cambios en MongoDB.

    Returns:
        Monitor CDC configurado
    """
    logger.info("Configurando monitor CDC...")

    monitor = crear_monitor_cdc(
        nombre_cola=configuracion.obtener_rabbitmq_cola_cambios(),
        colecciones=["documentos", "recursos", "archivos"],
        filtro_operaciones=["insert", "update", "replace"],
    )

    return monitor


def verificar_infraestructura():
    """
    Verifica que toda la infraestructura esté disponible y correctamente configurada.

    Returns:
        True si toda la infraestructura está disponible, False en caso contrario
    """
    logger.info("Verificando infraestructura...")

    # Verificar MongoDB
    try:
        mongodb = ConectorMongoDB(
            host=configuracion.obtener_mongodb_host(),
            puerto=configuracion.obtener_mongodb_puerto(),
            usuario=configuracion.obtener_mongodb_usuario(),
            contraseña=configuracion.obtener_mongodb_contraseña(),
            base_datos=configuracion.obtener_mongodb_base_datos(),
        )
        if mongodb.esta_conectado():
            logger.success("Conexión a MongoDB OK")
        else:
            logger.error("No se pudo conectar a MongoDB")
            return False
    except Exception as e:
        logger.error(f"Error al verificar MongoDB: {e}")
        return False

    # Verificar RabbitMQ
    try:
        rabbitmq = ConectorRabbitMQ()
        if rabbitmq.conectar():
            cola = configuracion.obtener_rabbitmq_cola_cambios()
            if rabbitmq.declarar_cola(cola):
                logger.success(f"Conexión a RabbitMQ OK, cola '{cola}' verificada")
            else:
                logger.error(f"No se pudo declarar la cola {cola}")
                return False
        else:
            logger.error("No se pudo conectar a RabbitMQ")
            return False
    except Exception as e:
        logger.error(f"Error al verificar RabbitMQ: {e}")
        return False

    # Verificar Qdrant
    try:
        qdrant = ConectorQdrant()
        if qdrant.esta_conectado():
            colecciones = qdrant.listar_colecciones()
            logger.info(
                f"Conexión a Qdrant OK, colecciones disponibles: {len(colecciones)}"
            )

            # Verificar colección para el curso
            prefijo = configuracion.obtener("QDRANT_COLLECTION_PREFIX", "curso_")
            coleccion = f"{prefijo}1"  # Para el ejemplo usamos curso_1

            colecciones_names = [c.get("nombre") for c in colecciones]
            if coleccion not in colecciones_names:
                # Obtener dimensión de embeddings configurada
                dimension = int(
                    configuracion.obtener("QDRANT_DIMENSION_EMBEDDINGS", "384")
                )

                logger.info(
                    f"Creando colección '{coleccion}' con dimensión {dimension}"
                )
                if not qdrant.crear_coleccion(coleccion, dimension):
                    logger.error(f"No se pudo crear la colección {coleccion}")
                    return False
                logger.info(f"Colección '{coleccion}' creada")
            else:
                logger.info(f"Colección '{coleccion}' ya existe")
        else:
            logger.error("No se pudo conectar a Qdrant")
            return False
    except Exception as e:
        logger.error(f"Error al verificar Qdrant: {e}")
        return False

    # Verificar Ollama (opcional)
    if configuracion.obtener("USAR_OLLAMA", "false").lower() == "true":
        try:
            import ollama

            response = ollama.list()
            modelos = response.get("models", [])
            logger.success(f"Conexión a Ollama OK, modelos disponibles: {len(modelos)}")

            # Verificar si los modelos necesarios están disponibles
            modelo_texto = configuracion.obtener("MODELO_TEXTO", "llama3")
            modelo_encontrado = any(m.get("name") == modelo_texto for m in modelos)

            if modelo_encontrado:
                logger.success(f"Modelo de texto '{modelo_texto}' disponible")
            else:
                logger.warning(f"Modelo de texto '{modelo_texto}' no disponible")
                logger.warning(
                    f"Puede que necesite descargar el modelo con: ollama pull {modelo_texto}"
                )
                logger.warning(
                    f"Modelos disponibles: {[m.get('name', '') for m in modelos]}"
                )

            # Si usa Ollama para embeddings, verificar modelo
            if (
                configuracion.obtener("USAR_OLLAMA_EMBEDDINGS", "false").lower()
                == "true"
            ):
                modelo_emb = configuracion.obtener(
                    "MODELO_EMBEDDING", "all-MiniLM-L6-v2"
                )
                modelo_emb_encontrado = any(
                    m.get("name") == modelo_emb for m in modelos
                )

                if modelo_emb_encontrado:
                    logger.success(f"Modelo de embedding '{modelo_emb}' disponible")
                else:
                    logger.warning(f"Modelo de embedding '{modelo_emb}' no disponible")
                    logger.warning(
                        f"Puede que necesite descargar el modelo con: ollama pull {modelo_emb}"
                    )
        except Exception as e:
            logger.warning(f"Advertencia: No se pudo conectar a Ollama: {e}")
            logger.warning(
                "El procesamiento continuará sin mejora de textos con Ollama"
            )

    logger.success("Toda la infraestructura está disponible")
    return True


def esperar_y_verificar_resultados(id_documento, max_tiempo=60):
    """
    Espera un tiempo y verifica los resultados en Qdrant.

    Args:
        id_documento: ID del documento a buscar
        max_tiempo: Tiempo máximo de espera en segundos

    Returns:
        True si se encontraron resultados, False en caso contrario
    """
    logger.info(f"Esperando hasta {max_tiempo} segundos para verificar resultados...")

    # Crear conector Qdrant
    qdrant = ConectorQdrant()
    prefijo = configuracion.obtener("QDRANT_COLLECTION_PREFIX", "curso_")
    coleccion = f"{prefijo}1"  # Para el ejemplo usamos curso_1

    # Verificar periódicamente
    tiempo_inicio = time.time()
    while (time.time() - tiempo_inicio) < max_tiempo:
        # Esperar un poco
        time.sleep(5)
        tiempo_transcurrido = time.time() - tiempo_inicio
        logger.info(
            f"Verificando resultados... ({tiempo_transcurrido:.1f}/{max_tiempo}s)"
        )

        # Buscar por el ID original
        try:
            resultados = qdrant.buscar_por_id_original(coleccion, id_documento)
            if resultados:
                logger.success(
                    f"¡Éxito! Se encontraron {len(resultados)} chunks en Qdrant."
                )
                return resultados
        except Exception as e:
            logger.warning(f"Error al buscar en Qdrant: {e}")

    logger.warning(f"No se encontraron resultados después de {max_tiempo} segundos")
    return None


def main():
    """Función principal que ejecuta el flujo completo."""
    logger.info("Iniciando ejemplo de flujo completo...")

    # 1. Verificar infraestructura
    if not verificar_infraestructura():
        logger.critical("La verificación de infraestructura falló. Abortando.")
        return

    # 2. Crear monitor CDC
    monitor = configurar_monitor_cdc()
    if not monitor.iniciar():
        logger.error("No se pudo iniciar el monitor CDC")
        return

    logger.info("Monitor CDC iniciado, esperando cambios...")

    # 3. Iniciar flujo ByteWax
    flujo_bytewax = None
    try:
        logger.info("Iniciando flujo ByteWax de procesamiento...")
        flujo_bytewax = crear_flujo_procesamiento()
        logger.success("Flujo ByteWax iniciado correctamente")
    except Exception as e:
        logger.warning(
            f"Advertencia: No se pudo iniciar el flujo ByteWax localmente: {e}"
        )
        logger.warning(
            "Asumiendo que el servicio ByteWax está ejecutándose como servicio separado"
        )

    # 4. Crear documento de ejemplo (esto debería desencadenar el proceso)
    documento = crear_ejemplo_documento()
    if not documento:
        logger.error("No se pudo crear el documento de ejemplo, abortando.")
        monitor.detener()
        if flujo_bytewax:
            flujo_bytewax.detener()
        return

    # 5. Esperar a que el flujo se complete y verificar resultados
    resultados = esperar_y_verificar_resultados(documento.id, max_tiempo=120)

    if resultados:
        logger.success(
            f"Flujo completo exitoso. Se encontraron {len(resultados)} chunks en Qdrant."
        )

        # Mostrar ejemplos de chunks
        for i, resultado in enumerate(resultados[:3]):  # Mostrar solo los primeros 3
            logger.info(f"Chunk {i + 1}:")
            logger.info(f"  Contexto: {resultado.get('contexto', 'Sin contexto')}")
            texto_preview = resultado.get("texto", "")[:150]
            if len(resultado.get("texto", "")) > 150:
                texto_preview += "..."
            logger.info(f"  Texto: {texto_preview}")

        if len(resultados) > 3:
            logger.info(f"... y {len(resultados) - 3} chunks más")

        # Hacer una búsqueda de ejemplo
        try:
            logger.info(
                "\nRealizando búsqueda de ejemplo en la base de datos vectorial..."
            )

            # Crear conector y obtener nombre de colección
            qdrant = ConectorQdrant()
            prefijo = configuracion.obtener("QDRANT_COLLECTION_PREFIX", "curso_")
            coleccion = f"{prefijo}1"  # Para el ejemplo usamos curso_1

            query = "Qué es el aprendizaje supervisado"
            logger.info(f"Consulta: '{query}'")

            resultados_busqueda = qdrant.buscar_similares(
                texto=query, coleccion=coleccion, limite=3, umbral=0.6
            )

            if resultados_busqueda:
                logger.success(
                    f"Búsqueda exitosa. Se encontraron {len(resultados_busqueda)} resultados."
                )
                for i, resultado in enumerate(resultados_busqueda):
                    logger.info(f"Resultado {i + 1}:")
                    logger.info(f"  Similitud: {resultado.get('score', 0):.2f}")
                    logger.info(
                        f"  Contexto: {resultado.get('contexto', 'Sin contexto')}"
                    )
                    texto_preview = resultado.get("texto", "")[:150]
                    if len(resultado.get("texto", "")) > 150:
                        texto_preview += "..."
                    logger.info(f"  Texto: {texto_preview}")
            else:
                logger.warning("No se encontraron resultados en la búsqueda")

        except Exception as e:
            logger.error(f"Error al realizar búsqueda: {e}")
    else:
        logger.warning("No se pudo verificar el resultado del procesamiento en Qdrant")
        logger.info("Posibles causas:")
        logger.info(
            "- El servicio ByteWax no está procesando correctamente los mensajes"
        )
        logger.info("- El tiempo de espera no fue suficiente")
        logger.info("- Error en la generación de embeddings")
        logger.info("- Problema de conexión con Qdrant")

        # Intentar verificar manualmente si hay algo en la colección
        try:
            # Crear conector y obtener nombre de colección
            qdrant = ConectorQdrant()
            prefijo = configuracion.obtener("QDRANT_COLLECTION_PREFIX", "curso_")
            coleccion = f"{prefijo}1"  # Para el ejemplo usamos curso_1

            colecciones = qdrant.listar_colecciones()
            for col in colecciones:
                nombre = col.get("nombre")
                if nombre == coleccion:
                    puntos = col.get("puntos", 0)
                    logger.info(
                        f"La colección '{coleccion}' existe y tiene {puntos} puntos"
                    )
                    if puntos == 0:
                        logger.warning(
                            "La colección está vacía, no se han insertado documentos"
                        )
                    break
            else:
                logger.warning(f"La colección '{coleccion}' no existe")
        except Exception as e:
            logger.error(f"Error al verificar colecciones: {e}")

    # 7. Detener servicios
    logger.info("Deteniendo servicios...")

    if flujo_bytewax:
        flujo_bytewax.detener()
        logger.info("Flujo ByteWax detenido")

    monitor.detener()
    logger.info("Monitor CDC detenido")

    logger.info("Ejemplo de flujo completo finalizado")


if __name__ == "__main__":
    main()
