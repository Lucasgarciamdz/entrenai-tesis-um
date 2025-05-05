#!/usr/bin/env python
"""
Ejemplo de flujo completo de procesamiento de archivos de Moodle.

Este script demuestra el flujo completo desde la descarga de archivos
de Moodle hasta su procesamiento y almacenamiento en la base de datos vectorial.
"""

import sys
import os
import time
import json
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
from app.database.modelos_documentos import DocumentoBase, ContenidoTexto, DocumentoPDF
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
        base_datos=configuracion.obtener_mongodb_base_datos()
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
            "etiquetas": ["machine learning", "ia", "introducción"]
        }
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
        filtro_operaciones=["insert", "update", "replace"]
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
            base_datos=configuracion.obtener_mongodb_base_datos()
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
            logger.info(f"Conexión a Qdrant OK, colecciones disponibles: {len(colecciones)}")
            
            # Verificar colección para el curso
            coleccion = "curso_1"  # Para el ejemplo usamos curso_1
            if coleccion not in [c.get('nombre') for c in colecciones]:
                if not qdrant.crear_coleccion(coleccion, dimension=384):
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
            logger.success(f"Conexión a Ollama OK, modelos disponibles: {len(response.get('models', []))}")
        except Exception as e:
            logger.warning(f"Advertencia: No se pudo conectar a Ollama: {e}")
            logger.warning("El procesamiento continuará sin mejora de textos con Ollama")
    
    logger.success("Toda la infraestructura está disponible")
    return True


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
    
    # 3. Iniciar flujo ByteWax (opcional - puede ejecutarse como servicio separado)
    flujo_bytewax = None
    try:
        logger.info("Iniciando flujo ByteWax de procesamiento...")
        flujo_bytewax = crear_flujo_procesamiento()
        logger.success("Flujo ByteWax iniciado correctamente")
    except Exception as e:
        logger.warning(f"Advertencia: No se pudo iniciar el flujo ByteWax localmente: {e}")
        logger.warning("Asumiendo que el servicio ByteWax está ejecutándose como servicio separado")
    
    # 4. Crear documento de ejemplo (esto debería desencadenar el proceso)
    documento = crear_ejemplo_documento()
    if not documento:
        monitor.detener()
        if flujo_bytewax:
            flujo_bytewax.detener()
        return
    
    # 5. Esperar a que el flujo se complete
    logger.info("Documento creado. El CDC debería detectar el cambio y publicarlo en RabbitMQ")
    logger.info("ByteWax debería procesar el mensaje y guardarlo en Qdrant")
    logger.info("Esperando 60 segundos para que el proceso termine...")
    
    # Imprimir progreso
    for i in range(12):
        time.sleep(5)
        logger.info(f"Esperando... {(i+1)*5}/60 segundos")
    
    # 6. Verificar resultado en Qdrant
    qdrant = ConectorQdrant()
    coleccion = "curso_1"
    
    # Buscar por el ID original
    resultados = qdrant.buscar_por_id_original(coleccion, documento.id)
    if resultados:
        logger.success(f"¡Flujo completo exitoso! Documento encontrado en Qdrant: {len(resultados)} chunks")
        for i, resultado in enumerate(resultados[:2]):  # Mostrar solo los primeros 2 para no saturar el log
            logger.info(f"Chunk {i+1}: {resultado['texto'][:100]}...")
        
        if len(resultados) > 2:
            logger.info(f"... y {len(resultados) - 2} chunks más")
    else:
        logger.warning("No se encontró el documento en Qdrant. Es posible que el procesamiento no haya terminado.")
        logger.info("Verificando si hay algún documento en la colección...")
        
        # Intentar buscar cualquier documento
        try:
            colecciones = qdrant.listar_colecciones()
            for coleccion_info in colecciones:
                if coleccion_info.get('nombre') == coleccion:
                    puntos = coleccion_info.get('puntos', 0)
                    if puntos > 0:
                        logger.info(f"La colección '{coleccion}' tiene {puntos} puntos, pero no se encontró el documento buscado")
                    else:
                        logger.warning(f"La colección '{coleccion}' está vacía")
        except Exception as e:
            logger.error(f"Error al verificar colecciones en Qdrant: {e}")
    
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