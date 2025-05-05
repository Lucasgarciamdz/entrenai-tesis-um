#!/usr/bin/env python
"""
Ejemplo de Flujo Completo: Moodle -> MongoDB -> CDC -> RabbitMQ -> ByteWax -> Qdrant.

Este script demuestra el flujo completo:
1. Descarga recursos (PDFs) de un curso específico de Moodle.
2. Procesa los PDFs para extraer texto.
3. Guarda el texto extraído en MongoDB.
4. (Asume) El CDC detecta el cambio y envía un mensaje a RabbitMQ.
5. (Asume) El servicio ByteWax consume el mensaje, procesa el texto (Markdown, chunks, embeddings).
6. (Asume) ByteWax guarda los embeddings en Qdrant.
7. Verifica que los datos (o al menos el conteo) aparezcan en Qdrant.
"""
import time
import threading
import sys
import json
from loguru import logger
from pathlib import Path
from bson import json_util # Needed if CDC monitor part is fully implemented here

# Importar módulos del proyecto
try:
    from app.config import configuracion
    from app.clientes import ClienteMoodle, ExtractorRecursosMoodle
    from app.procesadores_archivos import ProcesadorArchivos
    from app.database.conector_mongodb import ConectorMongoDB
    from app.database.conector_qdrant import conector_qdrant # Import instance directly
    from app.database.conector_rabbitmq import conector_rabbitmq # Import instance directly
    # Assuming crear_monitor_cdc exists and is the intended way to start CDC
    from app.database.cdc_mongodb import crear_monitor_cdc, MonitorCambiosMongoDB
    # Assuming crear_flujo_procesamiento exists for ByteWax setup
    from app.procesamiento_bytewax.flujo_bytewax import crear_flujo_procesamiento, FlujoByteWax
    # Import the specific model used for storing processed text
    from app.database.modelos_documentos import DocumentoPDF, ContenidoTexto # Choose the correct one
except ImportError as e:
    print(f"Error importando módulos: {e}. Asegúrate de que PYTHONPATH esté configurado o ejecuta desde la raíz.")
    sys.exit(1)

# --- Configuración del Logger ---
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    colorize=True
)
log_file_path = "ejemplo_flujo_completo.log"
logger.add(
    log_file_path,
    level="DEBUG",
    rotation="10 MB",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)

# --- Variables Globales para Hilos (Opcional, si se ejecutan aquí) ---
cdc_monitor_thread = None
bytewax_flow_thread = None
stop_event = threading.Event()

# --- Funciones Target para Hilos (Opcional) ---
def run_cdc_monitor(monitor: MonitorCambiosMongoDB):
    """Función target para el hilo del monitor CDC."""
    logger.info("Iniciando monitor CDC en hilo separado...")
    try:
        # Asumiendo que el monitor tiene un método run() o start() que bloquea
        # y que puede ser detenido por un evento o similar.
        # Esta parte necesita adaptación basada en la implementación real de MonitorCambiosMongoDB.
        # Ejemplo hipotético:
        # monitor.run(stop_event)
        logger.warning("La ejecución real del monitor CDC en hilo no está implementada aquí. Ejecútalo externamente.")
        # Simulación de ejecución
        while not stop_event.is_set():
            time.sleep(1)
    except Exception as e:
        logger.error(f"Error en el hilo del monitor CDC: {e}")
    finally:
        logger.info("Hilo del monitor CDC detenido.")

def run_bytewax_flow(flow: FlujoByteWax):
    """Función target para el hilo del flujo ByteWax."""
    logger.info("Iniciando flujo ByteWax en hilo separado...")
    try:
        # La ejecución de ByteWax generalmente requiere `bytewax.run` o un ejecutor específico.
        # Esta parte necesita adaptación basada en cómo se ejecuta tu FlujoByteWax.
        # Ejemplo hipotético:
        # flow.run(stop_event)
        logger.warning("La ejecución real del flujo ByteWax en hilo no está implementada aquí. Ejecútalo externamente.")
        # Simulación de ejecución
        while not stop_event.is_set():
            time.sleep(1)
    except Exception as e:
        logger.error(f"Error en el hilo del flujo ByteWax: {e}")
    finally:
        logger.info("Hilo del flujo ByteWax detenido.")

# --- Función Principal ---
def main():
    global cdc_monitor_thread, bytewax_flow_thread

    logger.info("--- Iniciando Ejemplo Flujo Completo ---")
    logger.info(f"Logs detallados en: {log_file_path}")

    # 1. Cargar Configuración
    try:
        URL_MOODLE = configuracion.obtener_url_moodle()
        TOKEN_MOODLE = configuracion.obtener_token_moodle()
        DIR_DESCARGAS = configuracion.obtener_directorio_descargas()
        MONGO_HOST = configuracion.obtener_mongodb_host()
        MONGO_PUERTO = configuracion.obtener_mongodb_puerto()
        MONGO_USER = configuracion.obtener_mongodb_usuario()
        MONGO_PASS = configuracion.obtener_mongodb_contraseña()
        MONGO_DB = configuracion.obtener_mongodb_base_datos()
        RABBITMQ_QUEUE = configuracion.obtener("RABBITMQ_QUEUE_NAME", "moodle_changes")
        QDRANT_COLLECTION_PREFIX = configuracion.obtener("QDRANT_COLLECTION_PREFIX", "curso_")
        # Determinar la colección MongoDB a monitorear
        # Usar DocumentoPDF si existe y es el modelo correcto, si no, ContenidoTexto o un default
        if 'DocumentoPDF' in globals() and hasattr(DocumentoPDF, 'Settings') and hasattr(DocumentoPDF.Settings, 'name'):
             COLLECTION_TO_MONITOR = DocumentoPDF.Settings.name
             ModelToSave = DocumentoPDF
        elif 'ContenidoTexto' in globals() and hasattr(ContenidoTexto, 'Settings') and hasattr(ContenidoTexto.Settings, 'name'):
             COLLECTION_TO_MONITOR = ContenidoTexto.Settings.name
             ModelToSave = ContenidoTexto
        else:
             logger.warning("No se pudo determinar la colección MongoDB desde los modelos. Usando 'documentos'.")
             COLLECTION_TO_MONITOR = "documentos" # Ajustar si es necesario
             ModelToSave = ContenidoTexto # Asumir ContenidoTexto como fallback

        logger.info(f"Colección MongoDB a monitorear/guardar: {COLLECTION_TO_MONITOR}")
        logger.info(f"Cola RabbitMQ: {RABBITMQ_QUEUE}")
        logger.info(f"Prefijo Colección Qdrant: {QDRANT_COLLECTION_PREFIX}")

        # Asegurar que el directorio de descargas exista
        Path(DIR_DESCARGAS).mkdir(parents=True, exist_ok=True)
        logger.info(f"Directorio de descargas: {DIR_DESCARGAS}")

    except Exception as e:
        logger.critical(f"Error fatal al cargar la configuración: {e}")
        return

    # 2. Inicializar Conectores
    conector_mongodb = None
    cdc_monitor = None
    # bytewax_flow = None # La creación puede ser compleja

    try:
        logger.info("Conectando a MongoDB...")
        conector_mongodb = ConectorMongoDB(
            host=MONGO_HOST,
            puerto=MONGO_PUERTO,
            usuario=MONGO_USER,
            contraseña=MONGO_PASS,
            base_datos=MONGO_DB,
        )
        if not conector_mongodb.conectar():
            raise ConnectionError("No se pudo conectar a MongoDB.")
        logger.success("Conectado a MongoDB.")

        logger.info("Conectando a Qdrant...")
        if not conector_qdrant.conectar():
             raise ConnectionError("No se pudo conectar a Qdrant.")
        logger.success("Conectado a Qdrant.")

        logger.info("Conectando a RabbitMQ...")
        if not conector_rabbitmq.conectar():
             raise ConnectionError("No se pudo conectar a RabbitMQ.")
        logger.success("Conectado a RabbitMQ.")

        # 3. Iniciar Servicios en Hilos (CDC y ByteWax) - OPCIONAL
        # --- CDC ---
        logger.info("Configurando monitor CDC...")
        # Descomentar y adaptar si se quiere ejecutar en hilo aquí
        # cdc_monitor = crear_monitor_cdc(
        #      host=MONGO_HOST, puerto=MONGO_PUERTO, usuario=MONGO_USER, contraseña=MONGO_PASS,
        #      base_datos=MONGO_DB, cola=RABBITMQ_QUEUE,
        #      colecciones=[COLLECTION_TO_MONITOR], filtro_operaciones=["insert"]
        # )
        # cdc_monitor_thread = threading.Thread(target=run_cdc_monitor, args=(cdc_monitor,), daemon=True)
        # cdc_monitor_thread.start()
        logger.warning("Inicio del monitor CDC omitido. Asegúrate de que 'servicio_cdc.py' esté ejecutándose.")

        # --- ByteWax ---
        logger.info("Configurando flujo ByteWax...")
        # Descomentar y adaptar si se quiere ejecutar en hilo aquí
        # bytewax_flow = crear_flujo_procesamiento()
        # bytewax_flow_thread = threading.Thread(target=run_bytewax_flow, args=(bytewax_flow,), daemon=True)
        # bytewax_flow_thread.start()
        logger.warning("Inicio del flujo ByteWax omitido. Asegúrate de que 'servicio_bytewax.py' esté ejecutándose.")

        # Dar tiempo a los servicios externos (si se ejecutan fuera) para estar listos
        logger.info("Esperando 5 segundos para que los servicios externos (CDC/ByteWax) estén listos...")
        time.sleep(5)

        # 4. Descargar Recursos de Moodle
        logger.info("Inicializando cliente Moodle y extractor...")
        cliente_moodle = ClienteMoodle(url_base=URL_MOODLE, token=TOKEN_MOODLE)
        extractor = ExtractorRecursosMoodle(cliente=cliente_moodle, directorio_destino=DIR_DESCARGAS)

        id_curso = 2
        tipos_recursos = ['resource'] # 'resource' suele incluir archivos como PDF, DOCX, etc.
        max_archivos_a_procesar = 2 # Limitar para el ejemplo
        logger.info(f"Intentando descargar hasta {max_archivos_a_procesar} recursos tipo '{tipos_recursos}' del curso ID {id_curso}...")

        try:
            resultados_descarga = extractor.descargar_recursos_curso(
                id_curso=id_curso, tipos_recursos=tipos_recursos
            )
            archivos_descargados = resultados_descarga.get('resource', [])

            if not archivos_descargados:
                logger.warning(f"No se encontraron recursos tipo '{tipos_recursos}' para descargar en el curso {id_curso}.")
                # Considerar si continuar o no. Por ahora, salimos.
                return

            logger.info(f"Descargados {len(archivos_descargados)} archivos tipo 'resource'.")
            # Filtrar solo PDFs y limitar
            archivos_pdf_a_procesar = [p for p in archivos_descargados if Path(p).suffix.lower() == ".pdf"][:max_archivos_a_procesar]

            if not archivos_pdf_a_procesar:
                logger.warning(f"No se encontraron archivos PDF entre los {len(archivos_descargados)} descargados.")
                return

            logger.info(f"Se procesarán los siguientes {len(archivos_pdf_a_procesar)} archivos PDF: {archivos_pdf_a_procesar}")

        except Exception as e:
            logger.error(f"Error durante la descarga de Moodle: {e}", exc_info=True)
            return

        # 5. Procesar Archivos y Guardar en MongoDB (Disparando CDC)
        logger.info("Inicializando procesador de archivos...")
        procesador_archivos = ProcesadorArchivos()
        ids_documentos_guardados = []
        documentos_fallidos = []

        for ruta_pdf in archivos_pdf_a_procesar:
            nombre_archivo = Path(ruta_pdf).name
            logger.info(f"Procesando archivo: {nombre_archivo}")
            try:
                # procesar_archivo devuelve un dict con 'texto', 'metadatos', etc.
                datos_procesados = procesador_archivos.procesar_archivo(ruta_pdf)

                if datos_procesados and 'texto' in datos_procesados and datos_procesados['texto']:
                    texto_extraido = datos_procesados['texto']
                    metadatos = datos_procesados.get('metadatos', {})
                    logger.info(f"Texto extraído de {nombre_archivo} (longitud: {len(texto_extraido)}).")

                    # Crear instancia del modelo Pydantic
                    # Ajustar campos según la definición exacta de ModelToSave (DocumentoPDF o ContenidoTexto)
                    doc_data = {
                        "id_curso": id_curso,
                        "nombre_archivo": nombre_archivo,
                        "tipo_archivo": "pdf",
                        "texto": texto_extraido,
                        "metadatos": metadatos,
                        # Añadir otros campos necesarios por el modelo, e.g.:
                        # "nombre_curso": f"Curso {id_curso}", # Obtener nombre real si es posible
                        # "id_moodle_recurso": None, # Obtener si es posible/necesario
                        # "ruta_archivo": ruta_pdf, # Opcional, para referencia
                    }
                    # Filtrar Nones si el modelo no los acepta o tiene defaults
                    doc_data_cleaned = {k: v for k, v in doc_data.items() if v is not None}
                    documento_a_guardar = ModelToSave(**doc_data_cleaned)


                    logger.info(f"Guardando documento procesado en MongoDB (Colección: {COLLECTION_TO_MONITOR})...")
                    # El método guardar de ConectorMongoDB debería manejar la conversión a dict y _id
                    doc_id = conector_mongodb.guardar(documento_a_guardar)

                    if doc_id:
                        logger.success(f"Documento '{nombre_archivo}' guardado en MongoDB con ID: {doc_id}. CDC debería activarse.")
                        ids_documentos_guardados.append(doc_id)
                    else:
                        logger.error(f"Error al guardar el documento de '{nombre_archivo}' en MongoDB.")
                        documentos_fallidos.append(nombre_archivo)
                else:
                    logger.warning(f"No se pudo extraer texto o procesar el archivo: {nombre_archivo}")
                    documentos_fallidos.append(nombre_archivo)

            except Exception as e:
                logger.error(f"Error procesando el archivo {nombre_archivo}: {e}", exc_info=True)
                documentos_fallidos.append(nombre_archivo)

        if not ids_documentos_guardados:
            logger.error("No se guardó ningún documento en MongoDB. El flujo no puede continuar.")
            return
        if documentos_fallidos:
             logger.warning(f"Archivos que fallaron en el procesamiento/guardado: {documentos_fallidos}")

        # 6. Esperar Procesamiento Asíncrono (CDC -> RabbitMQ -> ByteWax -> Qdrant)
        tiempo_espera = 60 # Segundos (ajustar según la velocidad esperada del pipeline ByteWax)
        logger.info(f"Esperando {tiempo_espera} segundos para el procesamiento asíncrono completo...")
        for i in range(tiempo_espera, 0, -5):
            logger.info(f"... {i}s restantes")
            time.sleep(5)
        logger.info("Tiempo de espera finalizado.")

        # 7. Verificar Qdrant
        logger.info("Verificando inserciones en Qdrant...")
        qdrant_collection_name = f"{QDRANT_COLLECTION_PREFIX}{id_curso}"
        logger.info(f"Buscando puntos en la colección Qdrant: '{qdrant_collection_name}'")

        try:
            # Verificar si la colección existe
            collections_info = conector_qdrant.cliente.get_collections()
            collection_names = [c.name for c in collections_info.collections]

            if qdrant_collection_name in collection_names:
                logger.info(f"La colección '{qdrant_collection_name}' existe.")
                # Contar puntos en la colección
                count_response = conector_qdrant.cliente.count(collection_name=qdrant_collection_name, exact=True)
                num_puntos = count_response.count
                logger.success(f"Verificación Qdrant: Se encontraron {num_puntos} puntos (chunks/embeddings) en la colección '{qdrant_collection_name}'.")
                # Podrías añadir una consulta scroll para ver algunos puntos si es necesario:
                # scroll_response = conector_qdrant.cliente.scroll(collection_name=qdrant_collection_name, limit=5, with_payload=True)
                # logger.debug(f"Primeros 5 puntos encontrados: {scroll_response}")
            else:
                logger.warning(f"Verificación Qdrant: La colección '{qdrant_collection_name}' NO existe aún o no se ha creado.")

        except Exception as e:
            logger.error(f"Error al verificar Qdrant: {e}", exc_info=True)

    except ConnectionError as e:
        logger.critical(f"Error de conexión inicial: {e}")
    except Exception as e:
        logger.critical(f"Error general inesperado en el script: {e}", exc_info=True)

    finally:
        # 8. Limpieza
        logger.info("Iniciando limpieza de recursos...")
        stop_event.set() # Señal para detener hilos (si se iniciaron aquí)

        # Esperar a los hilos si se iniciaron
        if cdc_monitor_thread and cdc_monitor_thread.is_alive():
            logger.info("Esperando al hilo del monitor CDC...")
            cdc_monitor_thread.join(timeout=5)
        if bytewax_flow_thread and bytewax_flow_thread.is_alive():
            logger.info("Esperando al hilo del flujo ByteWax...")
            bytewax_flow_thread.join(timeout=5)

        # Desconectar conectores
        if conector_mongodb:
            conector_mongodb.desconectar()
            logger.info("Desconectado de MongoDB.")
        # Los conectores singleton de Qdrant y RabbitMQ podrían no necesitar desconexión explícita
        # o manejarla internamente/al salir del script.
        # Verificamos si RabbitMQ tiene método desconectar y está conectado
        if conector_rabbitmq and hasattr(conector_rabbitmq, 'esta_conectado') and conector_rabbitmq.esta_conectado():
             if hasattr(conector_rabbitmq, 'desconectar'):
                 conector_rabbitmq.desconectar()
                 logger.info("Desconectado de RabbitMQ.")
             else:
                 logger.info("RabbitMQ no tiene método desconectar o ya está desconectado.")

        logger.info("--- Ejemplo Flujo Completo Finalizado ---")


if __name__ == "__main__":
    main()