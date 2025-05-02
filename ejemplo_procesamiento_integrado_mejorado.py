#!/usr/bin/env python
"""
Ejemplo Integrado Mejorado: Sistema completo de procesamiento de datos de Moodle.

Este script muestra el flujo completo del sistema:
1. Descarga recursos de Moodle (curso 2)
2. Procesa los archivos y extrae texto
3. Guarda en MongoDB
4. Detecta cambios con CDC
5. Envía cambios a RabbitMQ
6. Procesa con ByteWax (limpieza, chunks, contexto, embeddings)
7. Almacena en Qdrant
"""

import os
import sys
import time
import json
import threading
from typing import Dict, List, Any, Optional

from loguru import logger

from app.clientes import RecolectorMoodle
from app.procesadores_archivos import ProcesadorArchivos, ProcesadorPDF
from app.config.configuracion import configuracion
from app.database.modelos_documentos import (
    Curso,
    ContenidoTexto,
    DocumentoPDF,
)
from app.database.conector_mongodb import ConectorMongoDB
from app.database.conector_rabbitmq import ConectorRabbitMQ
from app.database.conector_qdrant import ConectorQdrant
from app.procesamiento_bytewax.utils import (
    limpiar_texto,
    convertir_a_markdown,
    dividir_en_trunks,
    generar_contexto,
    generar_embedding,
)

# Configurar logger - Formato más simple y legible
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>[{time:HH:mm:ss}]</green> <level>{level}</level> | {message}",
)


class ProcesadorIntegrado:
    """Clase que coordina el flujo completo de procesamiento."""

    def __init__(self):
        """Inicializa el procesador."""
        self.conector_mongodb = None
        self.conector_rabbitmq = None
        self.conector_qdrant = None
        self.monitor_cdc = None
        self.hilo_monitor = None
        self.consumidor_rabbitmq = None
        self.hilo_consumidor = None
        self.config = configuracion
        self.colecciones_creadas = set()
        self.documentos_procesados = []  # Lista para almacenar documentos procesados
        self.mensajes_cdc_procesados = 0

    def inicializar_conexiones(self):
        """Inicializa todas las conexiones a servicios externos."""
        logger.info("Inicializando conexiones...")

        # MongoDB
        db_host = self.config.obtener_mongodb_host()
        db_puerto = self.config.obtener_mongodb_puerto()
        db_usuario = self.config.obtener_mongodb_usuario()
        db_password = self.config.obtener_mongodb_contraseña()
        db_nombre = self.config.obtener_mongodb_base_datos()

        self.conector_mongodb = ConectorMongoDB(
            host=db_host,
            puerto=db_puerto,
            usuario=db_usuario,
            contraseña=db_password,
            base_datos=db_nombre,
        )
        logger.info("MongoDB: Conexión establecida")

        # RabbitMQ
        rabbitmq_host = self.config.obtener_rabbitmq_host()
        rabbitmq_puerto = self.config.obtener_rabbitmq_puerto()
        rabbitmq_usuario = self.config.obtener_rabbitmq_usuario()
        rabbitmq_password = self.config.obtener_rabbitmq_contraseña()
        rabbitmq_cola = self.config.obtener_rabbitmq_cola_cambios()

        self.conector_rabbitmq = ConectorRabbitMQ(
            host=rabbitmq_host,
            puerto=rabbitmq_puerto,
            usuario=rabbitmq_usuario,
            contraseña=rabbitmq_password,
        )
        self.conector_rabbitmq.conectar()
        logger.info("RabbitMQ: Conexión establecida")

        self.conector_rabbitmq.declarar_cola(rabbitmq_cola)
        logger.info(f"Cola '{rabbitmq_cola}' declarada en RabbitMQ")

        # Qdrant
        qdrant_host = self.config.obtener("QDRANT_HOST", "localhost")
        qdrant_puerto = int(self.config.obtener("QDRANT_PORT", "6333"))

        self.conector_qdrant = ConectorQdrant(host=qdrant_host, puerto=qdrant_puerto)
        if self.conector_qdrant.conectar():
            logger.info("Qdrant: Conexión establecida")
        else:
            logger.error("No se pudo establecer conexión con Qdrant")
            return False

        return True

    def descargar_recursos_moodle(self, id_curso: int = 2) -> bool:
        """
        Descarga recursos del curso especificado en Moodle.

        Args:
            id_curso: ID del curso en Moodle

        Returns:
            True si la descarga fue exitosa, False en caso contrario
        """
        logger.info(f"Descargando recursos del curso {id_curso} de Moodle...")

        try:
            # Crear recolector usando la configuración
            recolector = RecolectorMoodle(
                url_moodle=self.config.obtener_url_moodle(),
                token=self.config.obtener_token_moodle(),
                directorio_descargas=self.config.obtener_directorio_descargas(),
            )

            # Verificar que el curso existe
            cursos = recolector.cliente.obtener_cursos()
            curso_seleccionado = next(
                (c for c in cursos if c.get("id") == id_curso), None
            )

            if not curso_seleccionado:
                logger.error(f"El curso con ID {id_curso} no existe")
                return False

            nombre_curso = curso_seleccionado.get("fullname", f"Curso {id_curso}")
            logger.info(f"Procesando curso: {nombre_curso}")

            # Guardar información del curso en MongoDB
            curso_documento = Curso(
                id_moodle=id_curso,
                nombre=nombre_curso,
                codigo=curso_seleccionado.get("shortname", ""),
                descripcion=curso_seleccionado.get("summary", ""),
            )

            # Guardar curso en MongoDB
            id_doc_curso = self.conector_mongodb.guardar(curso_documento)
            if id_doc_curso:
                logger.info(f"Curso guardado en MongoDB (ID: {id_doc_curso})")
            else:
                logger.error("Error al guardar curso en MongoDB")
                return False

            # Descargar recursos del curso
            tipos_recursos = self.config.obtener_tipos_recursos_default()
            logger.info(f"Tipos de recursos a descargar: {', '.join(tipos_recursos)}")

            archivos_descargados = recolector.extractor.descargar_recursos_curso(
                id_curso, tipos_recursos
            )

            # Mostrar resumen de archivos descargados
            total_archivos = sum(
                len(archivos) for archivos in archivos_descargados.values()
            )
            if total_archivos == 0:
                logger.warning("No se encontraron archivos para descargar")
                return False

            logger.info(f"Se descargaron {total_archivos} archivos en total")
            for tipo, archivos in archivos_descargados.items():
                if archivos:
                    logger.info(f"  - {len(archivos)} archivos de tipo '{tipo}'")

            # Retornar archivos descargados para su procesamiento
            return self.procesar_archivos_descargados(
                id_curso, nombre_curso, archivos_descargados
            )

        except Exception as e:
            logger.error(f"Error al descargar recursos: {e}")
            return False

    def procesar_archivos_descargados(
        self,
        id_curso: int,
        nombre_curso: str,
        archivos_descargados: Dict[str, List[str]],
    ) -> bool:
        """
        Procesa los archivos descargados y los guarda en MongoDB.

        Args:
            id_curso: ID del curso en Moodle
            nombre_curso: Nombre del curso
            archivos_descargados: Diccionario con archivos descargados

        Returns:
            True si el procesamiento fue exitoso, False en caso contrario
        """
        logger.info("Procesando archivos descargados...")

        try:
            # Aplanar la lista de archivos para procesamiento
            todos_archivos = []
            for tipo, archivos in archivos_descargados.items():
                todos_archivos.extend(archivos)

            # Separar archivos por tipo
            archivos_simples = []
            archivos_complejos = []

            for ruta_archivo in todos_archivos:
                _, extension = os.path.splitext(ruta_archivo)
                extension = extension.lower().lstrip(".")

                # Los archivos simples son procesados más rápido
                if extension in ["txt", "htm", "html", "md", "markdown"]:
                    archivos_simples.append(ruta_archivo)
                else:
                    archivos_complejos.append(ruta_archivo)

            logger.info(f"Archivos a procesar: {len(todos_archivos)}")
            logger.info(f"  - Archivos simples: {len(archivos_simples)}")
            logger.info(f"  - Archivos complejos: {len(archivos_complejos)}")

            # Procesar archivos simples
            for ruta_archivo in archivos_simples:
                documento = self.procesar_archivo(ruta_archivo, id_curso, nombre_curso)
                if documento:
                    self.documentos_procesados.append(documento)

            # Procesar archivos complejos
            for ruta_archivo in archivos_complejos:
                documento = self.procesar_archivo(ruta_archivo, id_curso, nombre_curso)
                if documento:
                    self.documentos_procesados.append(documento)

            # Mostrar resumen
            logger.info(
                f"Se procesaron {len(self.documentos_procesados)} de {len(todos_archivos)} archivos"
            )
            return len(self.documentos_procesados) > 0

        except Exception as e:
            logger.error(f"Error al procesar archivos: {e}")
            return False

    def procesar_archivo(
        self, ruta_archivo: str, id_curso: int, nombre_curso: str
    ) -> Optional[ContenidoTexto]:
        """
        Procesa un archivo y lo guarda en MongoDB.

        Args:
            ruta_archivo: Ruta al archivo a procesar
            id_curso: ID del curso al que pertenece el archivo
            nombre_curso: Nombre del curso

        Returns:
            Modelo de documento guardado o None si falla
        """
        nombre_archivo = os.path.basename(ruta_archivo)
        logger.info(f"Procesando archivo: {nombre_archivo}")

        try:
            # Obtener extensión del archivo
            _, extension = os.path.splitext(ruta_archivo)
            extension = extension.lower().lstrip(".")

            # Seleccionar tipo de procesamiento según la extensión
            documento = None

            if extension in ["txt", "md", "markdown"]:
                # Procesar archivo de texto simple
                with open(ruta_archivo, "r", encoding="utf-8") as f:
                    texto = f.read()

                documento = ContenidoTexto(
                    id_curso=id_curso,
                    nombre_curso=nombre_curso,
                    ruta_archivo=ruta_archivo,
                    nombre_archivo=nombre_archivo,
                    tipo_archivo=extension,
                    texto=texto,
                    metadatos={},
                )

            elif extension in ["html", "htm"]:
                # Procesar HTML
                with open(ruta_archivo, "r", encoding="utf-8") as f:
                    texto_html = f.read()

                # Crear procesador para extraer texto limpio
                procesador_archivos = ProcesadorArchivos()
                procesador = procesador_archivos.obtener_procesador(ruta_archivo)

                if procesador:
                    resultado = procesador.procesar_archivo(ruta_archivo)
                    texto = resultado.get("texto", texto_html)
                else:
                    texto = texto_html

                documento = ContenidoTexto(
                    id_curso=id_curso,
                    nombre_curso=nombre_curso,
                    ruta_archivo=ruta_archivo,
                    nombre_archivo=nombre_archivo,
                    tipo_archivo=extension,
                    texto=texto,
                    metadatos={},
                )

            elif extension == "pdf":
                # Procesar PDF con OCR
                procesador = ProcesadorPDF(usar_ocr=True, idioma="es")
                resultado = procesador.procesar_archivo(ruta_archivo)

                if not resultado or "texto" not in resultado:
                    logger.error(f"No se pudo extraer texto de {nombre_archivo}")
                    return None

                documento = DocumentoPDF(
                    id_curso=id_curso,
                    nombre_curso=nombre_curso,
                    ruta_archivo=ruta_archivo,
                    nombre_archivo=nombre_archivo,
                    texto=resultado["texto"],
                    metadatos=resultado.get("metadatos", {}),
                    total_paginas=resultado.get("metadatos", {}).get(
                        "numero_paginas", 0
                    ),
                    procesado_con_ocr=True,
                    contiene_formulas=resultado.get("contiene_formulas", False),
                    tiene_imagenes=bool(resultado.get("imagenes", [])),
                )

            else:
                # Intentar procesar con el procesador genérico
                procesador_archivos = ProcesadorArchivos()
                procesador = procesador_archivos.obtener_procesador(ruta_archivo)

                if not procesador:
                    logger.warning(
                        f"No hay procesador disponible para {nombre_archivo}"
                    )
                    return None

                resultado = procesador.procesar_archivo(ruta_archivo)

                if not resultado or "texto" not in resultado:
                    logger.error(f"No se pudo extraer texto de {nombre_archivo}")
                    return None

                documento = ContenidoTexto(
                    id_curso=id_curso,
                    nombre_curso=nombre_curso,
                    ruta_archivo=ruta_archivo,
                    nombre_archivo=nombre_archivo,
                    tipo_archivo=extension,
                    texto=resultado["texto"],
                    metadatos=resultado.get("metadatos", {}),
                )

            # Guardar documento en MongoDB
            if documento:
                id_documento = self.conector_mongodb.guardar(documento)

                if id_documento:
                    documento.id = id_documento
                    logger.info(
                        f"Documento guardado: {nombre_archivo} (ID: {id_documento})"
                    )
                    return documento
                else:
                    logger.error(f"Error al guardar {nombre_archivo} en MongoDB")

            return None

        except Exception as e:
            logger.error(f"Error al procesar {nombre_archivo}: {e}")
            return None

    def iniciar_monitor_cdc(self):
        """Inicia el monitor de cambios en la base de datos."""
        logger.info("Iniciando monitor CDC...")

        # Obtener credenciales de MongoDB
        db_host = self.config.obtener_mongodb_host()
        db_puerto = self.config.obtener_mongodb_puerto()
        db_usuario = self.config.obtener_mongodb_usuario()
        db_password = self.config.obtener_mongodb_contraseña()
        db_nombre = self.config.obtener_mongodb_base_datos()
        cola_cambios = self.config.obtener_rabbitmq_cola_cambios()

        # Iniciar monitor de cambios
        from app.database.cdc_mongodb import crear_monitor_cdc

        self.monitor_cdc = crear_monitor_cdc(
            host=db_host,
            puerto=db_puerto,
            usuario=db_usuario,
            contraseña=db_password,
            base_datos=db_nombre,
            cola=cola_cambios,
            # Colecciones a monitorear - Opcional, si no se especifica monitorea todas
            colecciones=["cursos", "recursos", "archivos"],
            # Operaciones a monitorear - Opcional
            filtro_operaciones=["insert", "update", "replace", "delete"],
        )

        logger.info("Monitor CDC iniciado correctamente")

    def iniciar_consumidor_rabbitmq(self):
        """Inicia el consumidor de mensajes de RabbitMQ."""
        logger.info("Iniciando consumidor de RabbitMQ...")

        # Obtener nombre de la cola
        cola_cambios = self.config.obtener_rabbitmq_cola_cambios()

        # Configurar callback de procesamiento
        def callback_procesamiento(ch, method, properties, body):
            try:
                # Decodificar mensaje
                logger.info(f"Recibido mensaje de RabbitMQ: {body[:100]}...")
                mensaje = json.loads(body.decode("utf-8"))

                # Imprimir el mensaje para debugging
                logger.info(
                    f"Mensaje decodificado: {json.dumps(mensaje, default=str)[:200]}..."
                )

                # Procesar mensaje
                self.procesar_mensaje_cdc(mensaje)

                # Confirmar procesamiento
                try:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.info("Mensaje procesado y confirmado correctamente")
                except Exception as e:
                    # Ignorar errores de confirmación sin interrumpir el flujo
                    logger.debug(f"No se pudo confirmar mensaje: {e}")

            except json.JSONDecodeError as e:
                logger.error(f"Error decodificando mensaje JSON: {e}")
                logger.error(
                    f"Contenido del mensaje problemático: {body.decode('utf-8', errors='replace')}"
                )
                # Rechazar mensaje malformado
                try:
                    ch.basic_nack(delivery_tag=method.delivery_tag)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error procesando mensaje CDC: {e}")
                # Intentar rechazar el mensaje, pero sin fallar si hay un problema
                try:
                    ch.basic_nack(delivery_tag=method.delivery_tag)
                except Exception:
                    pass

        # Asegurar que tenemos una conexión activa
        if not self.conector_rabbitmq.esta_conectado():
            logger.warning("La conexión a RabbitMQ no está activa, reconectando...")
            if not self.conector_rabbitmq.conectar():
                logger.error("No se pudo conectar a RabbitMQ")
                return False

        # Crear un nuevo canal
        try:
            canal = self.conector_rabbitmq.conexion.channel()
            canal.basic_qos(prefetch_count=1)

            # Asegurar que la cola existe
            self.conector_rabbitmq.declarar_cola(cola_cambios)

            # Configurar consumidor
            canal.basic_consume(
                queue=cola_cambios,
                on_message_callback=callback_procesamiento,
                auto_ack=False,
            )

            # Iniciar consumidor en un hilo separado
            self.consumidor_rabbitmq = canal

            def consumir():
                while True:
                    try:
                        logger.info("Consumidor esperando mensajes...")
                        canal.start_consuming()
                    except Exception as e:
                        # Capturar cualquier error, esperar un momento y reintentar
                        logger.debug(f"Error en el consumidor, reintentando: {e}")
                        time.sleep(1)

                        # Si hemos detenido el procesamiento, salir del bucle
                        if not self.conector_rabbitmq.esta_conectado():
                            break

                        # Intentar reconectar si es necesario
                        try:
                            if not canal.is_open:
                                if self.conector_rabbitmq.esta_conectado():
                                    canal = self.conector_rabbitmq.conexion.channel()
                                    canal.basic_qos(prefetch_count=1)
                                    canal.basic_consume(
                                        queue=cola_cambios,
                                        on_message_callback=callback_procesamiento,
                                        auto_ack=False,
                                    )
                        except Exception:
                            # Si no se puede recuperar, esperar y continuar el bucle
                            time.sleep(2)

            self.hilo_consumidor = threading.Thread(target=consumir, daemon=True)
            self.hilo_consumidor.start()

            logger.info(f"Consumidor de RabbitMQ iniciado en cola '{cola_cambios}'")
            return True

        except Exception as e:
            logger.error(f"Error al iniciar consumidor de RabbitMQ: {e}")
            return False

    def ejecutar_flujo_completo(self, id_curso: int = 2):
        """
        Ejecuta el flujo completo de procesamiento.

        Args:
            id_curso: ID del curso en Moodle a procesar

        Returns:
            True si el procesamiento fue exitoso, False en caso contrario
        """
        logger.info("INICIANDO FLUJO COMPLETO DE PROCESAMIENTO")

        # Variables para conteo de documentos procesados
        self.documentos_procesados = []
        self.mensajes_cdc_procesados = 0

        try:
            # 1. Inicializar conexiones
            if not self.inicializar_conexiones():
                logger.error("Error al inicializar conexiones")
                return False

            # 2. Iniciar el consumidor de RabbitMQ (para procesar mensajes)
            if not self.iniciar_consumidor_rabbitmq():
                logger.error("Error al iniciar consumidor de RabbitMQ")
                return False

            # 3. Iniciar el monitor CDC
            self.iniciar_monitor_cdc()

            # 4. Descargar y procesar recursos de Moodle
            resultado_descarga = self.descargar_recursos_moodle(id_curso)
            if not resultado_descarga:
                logger.error("No se pudieron descargar recursos de Moodle")
                # No salimos, podría haber documentos ya en MongoDB que queremos procesar

            # 5. Publicar mensaje de prueba para verificar procesamiento
            logger.info("Publicando mensaje de prueba para verificar procesamiento...")
            self.publicar_mensaje_prueba()

            # 6. Esperar a que se procesen los mensajes de CDC
            logger.info("Esperando procesamiento de mensajes CDC...")

            # Esperar un tiempo prudencial para que se procesen los mensajes
            # Este tiempo debe ser suficiente para que los mensajes CDC se procesen
            for i in range(10):  # Aumentamos el tiempo de espera a 20 segundos
                logger.info(f"Esperando procesamiento... ({i + 1}/10)")
                time.sleep(2)  # Esperar en intervalos más cortos

                # Si ya hay mensajes procesados, salir del bucle
                if self.mensajes_cdc_procesados > 0:
                    logger.info(
                        f"Se han procesado {self.mensajes_cdc_procesados} mensajes CDC"
                    )
                    break

            # Verificar colecciones en Qdrant
            logger.info("Verificando colecciones en Qdrant...")
            try:
                if self.conector_qdrant.esta_conectado():
                    colecciones_detalle = self.conector_qdrant.listar_colecciones()
                    logger.info(f"Colecciones en Qdrant ({len(colecciones_detalle)}):")
                    for coleccion in colecciones_detalle:
                        nombre = coleccion.get("nombre", "desconocido")
                        puntos = coleccion.get("puntos", 0)
                        logger.info(f"  - {nombre}: {puntos} puntos")
                else:
                    logger.warning(
                        "No se pudo verificar colecciones en Qdrant (sin conexión)"
                    )
            except Exception as e:
                logger.error(f"Error al verificar colecciones en Qdrant: {e}")

            # Resumen de resultados
            logger.info("\nRESUMEN DEL FLUJO COMPLETO")
            logger.info(
                f"Documentos guardados en MongoDB: {len(self.documentos_procesados)}"
            )
            logger.info(f"Mensajes CDC procesados: {self.mensajes_cdc_procesados}")

            if self.conector_qdrant:
                # Aquí se podrían agregar consultas a Qdrant para verificar los datos
                if self.mensajes_cdc_procesados > 0:
                    logger.info("Los datos han sido procesados y almacenados en Qdrant")
                else:
                    logger.warning(
                        "No se detectaron mensajes CDC procesados. Verifica la configuración."
                    )

            logger.info("FLUJO COMPLETO FINALIZADO EXITOSAMENTE")

            return True

        except Exception as e:
            logger.error(f"Error durante el flujo completo: {e}")
            return False
        finally:
            # Limpiar recursos
            self.limpiar_recursos()

    def limpiar_recursos(self):
        """Limpia todos los recursos utilizados."""
        logger.info("Limpiando recursos...")

        # Detener consumidor
        if self.consumidor_rabbitmq:
            try:
                # Usar cancel_all en lugar de stop_consuming para evitar errores
                if hasattr(self.consumidor_rabbitmq, "cancel_all"):
                    self.consumidor_rabbitmq.cancel_all()
                elif hasattr(self.consumidor_rabbitmq, "stop_consuming"):
                    self.consumidor_rabbitmq.stop_consuming()
                # No fallar si no podemos detener el consumidor correctamente
            except Exception as e:
                logger.error(f"Error al detener el consumidor: {e}")
                # No es crítico, continuar con la limpieza

            # Cerrar el canal si está abierto
            try:
                if (
                    hasattr(self.consumidor_rabbitmq, "is_open")
                    and self.consumidor_rabbitmq.is_open
                ):
                    self.consumidor_rabbitmq.close()
            except Exception as e:
                logger.error(f"Error al cerrar el canal del consumidor: {e}")

        # Detener monitor CDC
        if self.monitor_cdc:
            try:
                self.monitor_cdc.detener()
            except Exception as e:
                logger.error(f"Error al detener el monitor CDC: {e}")

        # Cerrar conexiones
        if self.conector_mongodb:
            try:
                self.conector_mongodb.desconectar()
            except Exception as e:
                logger.error(f"Error al desconectar MongoDB: {e}")

        if self.conector_rabbitmq:
            try:
                self.conector_rabbitmq.desconectar()
            except Exception as e:
                logger.error(f"Error al desconectar RabbitMQ: {e}")

        if self.conector_qdrant:
            try:
                self.conector_qdrant.desconectar()
            except Exception as e:
                logger.error(f"Error al desconectar Qdrant: {e}")

        logger.info("Recursos limpiados")

    def procesar_mensaje_cdc(self, mensaje: Dict[str, Any]):
        """
        Procesa un mensaje de cambio de MongoDB recibido desde RabbitMQ.

        Args:
            mensaje: Mensaje CDC con información del cambio
        """
        try:
            # Imprimir el mensaje recibido para debug
            logger.info(
                f"CDC: Mensaje recibido: {json.dumps(mensaje, default=str)[:200]}..."
            )

            # Extraer información del mensaje según el formato CDC de MongoDB
            tipo_operacion = mensaje.get("operationType", "desconocida")
            ns = mensaje.get("ns", {})
            coleccion = ns.get("coll", "desconocida")
            documento_id = str(mensaje.get("documentKey", {}).get("_id", ""))

            # El documento completo está en fullDocument para inserts y updates
            documento = mensaje.get("fullDocument", {})

            logger.info(
                f"CDC: Procesando {tipo_operacion} en {coleccion}, ID: {documento_id}"
            )

            # Verificar si hay texto en el documento
            texto = documento.get("texto", "")
            if not texto and coleccion in ["archivos", "recursos"]:
                logger.warning(f"Documento sin texto: {documento_id}")
                return

            # Procesar según la operación y colección
            if tipo_operacion in ["insert", "update", "replace"] and coleccion in [
                "archivos",
                "recursos",
            ]:
                resultado = self._procesar_documento_texto(
                    documento_id, documento, tipo_operacion
                )
                # Incrementar contador global de mensajes procesados
                if hasattr(self, "mensajes_cdc_procesados"):
                    self.mensajes_cdc_procesados += 1
                logger.info(
                    f"CDC: Procesamiento {'exitoso' if resultado else 'fallido'} para documento {documento_id}"
                )
            elif tipo_operacion == "delete":
                logger.info(
                    f"Documento eliminado: {documento_id} (colección: {coleccion})"
                )
                # Aquí se podría eliminar de Qdrant si es necesario
            else:
                logger.info(f"Operación no procesable: {tipo_operacion} en {coleccion}")

        except Exception as e:
            logger.error(f"Error al procesar mensaje CDC: {e}")
            # Registrar el mensaje que causó el error para debugging
            logger.error(f"Mensaje problemático: {json.dumps(mensaje, default=str)}")

    def _procesar_documento_texto(
        self, id_doc: str, documento: Dict[str, Any], operacion: str
    ):
        """
        Procesa un documento con texto para transformarlo y guardarlo en Qdrant.

        Args:
            id_doc: ID del documento
            documento: Documento completo
            operacion: Tipo de operación CDC

        Returns:
            True si el procesamiento fue exitoso, False en caso contrario
        """
        try:
            texto = documento.get("texto", "")

            # PASO 1: Limpieza de texto
            logger.info(f"Limpiando texto del documento {id_doc}")
            texto_limpio = limpiar_texto(texto)
            texto_markdown = convertir_a_markdown(texto_limpio)

            # Metadatos para Qdrant
            metadatos = {
                "id_original": id_doc,
                "id_curso": documento.get("id_curso", ""),
                "nombre_curso": documento.get("nombre_curso", ""),
                "nombre_archivo": documento.get("nombre_archivo", ""),
                "tipo_archivo": documento.get("tipo_archivo", ""),
                "operacion": operacion,
            }

            # Verificar que el conector está funcionando
            if not self.conector_qdrant.esta_conectado():
                logger.warning("Conector Qdrant no está conectado, reconectando...")
                if not self.conector_qdrant.conectar():
                    logger.error("No se pudo reconectar a Qdrant")
                    return False

            # Guardar texto limpio
            logger.info(f"Guardando texto limpio en Qdrant para documento {id_doc}")
            resultado_texto = self.conector_qdrant.guardar_texto_limpio(
                id_texto=id_doc, texto=texto_markdown, metadatos=metadatos
            )

            if not resultado_texto:
                logger.error(f"Error al guardar texto limpio para documento {id_doc}")
                return False

            logger.info("Texto limpio guardado en Qdrant exitosamente")

            # PASO 2: División en chunks
            logger.info("Dividiendo texto en chunks")
            chunks = dividir_en_trunks(texto_markdown)
            logger.info(f"Se generaron {len(chunks)} chunks")

            # Crear colección específica para el curso si no existe
            id_curso = documento.get("id_curso", "")
            nombre_curso = documento.get("nombre_curso", "")
            nombre_coleccion = f"curso_{id_curso}"

            if nombre_coleccion not in self.colecciones_creadas:
                logger.info(f"Creando colección {nombre_coleccion} en Qdrant")
                resultado_coleccion = self.conector_qdrant.crear_coleccion(
                    nombre=nombre_coleccion,
                    descripcion=f"Embeddings del curso: {nombre_curso}",
                )

                if resultado_coleccion:
                    self.colecciones_creadas.add(nombre_coleccion)
                    logger.info(f"Colección {nombre_coleccion} creada exitosamente")
                else:
                    logger.error(f"Error al crear colección {nombre_coleccion}")
                    return False

            # Configuración para generación de embeddings
            # Usar OLLAMA si está disponible (cambiar modelo según sea necesario)
            usar_ollama = self.config.obtener("USAR_OLLAMA", "false").lower() == "true"
            modelo_embedding = self.config.obtener(
                "MODELO_EMBEDDING", "all-MiniLM-L6-v2"
            )

            if usar_ollama:
                logger.info(
                    f"Usando OLLAMA con modelo {modelo_embedding} para generar embeddings"
                )
            else:
                logger.info(
                    f"Usando sentence-transformers con modelo {modelo_embedding} para generar embeddings"
                )

            # PASO 3: Procesar cada chunk
            chunks_procesados = 0
            for i, chunk in enumerate(chunks):
                # Generar contexto (metadatos enriquecidos)
                contexto = generar_contexto(chunk)

                # Generar embedding
                logger.info(f"Generando embedding para chunk {i + 1}/{len(chunks)}")
                embedding = generar_embedding(
                    texto=chunk, modelo_nombre=modelo_embedding, usar_ollama=usar_ollama
                )

                if not embedding:
                    logger.error(f"Error al generar embedding para chunk {i + 1}")
                    continue

                # Guardar embedding en Qdrant
                id_embedding = f"{id_doc}_chunk_{i}"
                logger.info(f"Guardando embedding {id_embedding} en Qdrant")
                resultado_embedding = self.conector_qdrant.guardar_embedding(
                    id_embedding=id_embedding,
                    texto=chunk,
                    embedding=embedding,
                    texto_original_id=id_doc,
                    metadatos={
                        **metadatos,
                        "indice": i,
                        "total_chunks": len(chunks),
                        "contexto": contexto,
                    },
                    coleccion=nombre_coleccion,
                )

                if resultado_embedding:
                    chunks_procesados += 1
                else:
                    logger.error(f"Error al guardar embedding {id_embedding}")

            logger.info(
                f"Procesamiento completo del documento {id_doc}: {chunks_procesados}/{len(chunks)} chunks guardados"
            )

            return chunks_procesados > 0

        except Exception as e:
            logger.error(f"Error al procesar documento {id_doc}: {e}")
            return False

    def publicar_mensaje_prueba(self):
        """Publica un mensaje de prueba en la cola de RabbitMQ para verificar el procesamiento."""
        cola_cambios = self.config.obtener_rabbitmq_cola_cambios()

        # Crear mensaje de prueba en el formato esperado por procesar_mensaje_cdc
        mensaje_prueba = {
            "operationType": "insert",
            "ns": {"db": "moodle_analytics", "coll": "recursos"},
            "documentKey": {"_id": "test_document_id"},
            "fullDocument": {
                "_id": "test_document_id",
                "id_curso": 2,
                "nombre_curso": "Curso de prueba",
                "nombre_archivo": "documento_prueba.txt",
                "tipo_archivo": "txt",
                "texto": """
                Este es un documento de prueba para verificar el procesamiento de mensajes CDC.
                Este texto será procesado para generar embeddings y guardarlos en Qdrant.
                Si todo funciona correctamente, verás este documento en Qdrant.
                """,
            },
        }

        # Publicar mensaje
        if self.conector_rabbitmq.publicar_mensaje(cola_cambios, mensaje_prueba):
            logger.info("Mensaje de prueba publicado exitosamente")
            return True
        else:
            logger.error("Error al publicar mensaje de prueba")
            return False


def main():
    """Función principal."""
    logger.info("EJEMPLO INTEGRADO MEJORADO: PROCESAMIENTO COMPLETO")

    # Verificar servicios
    logger.info("Verificando que los servicios estén en ejecución...")
    logger.info("Se requieren: MongoDB, RabbitMQ y Qdrant")
    logger.info(
        "Si no están en ejecución, inicie con: docker-compose up -d mongodb rabbitmq qdrant"
    )

    respuesta = input("\n¿Continuar con el procesamiento? (s/n): ").strip().lower()

    if respuesta != "s":
        logger.info("Procesamiento cancelado")
        return

    # Pedir ID del curso
    id_curso = input("Ingrese el ID del curso a procesar (por defecto 2): ").strip()
    id_curso = int(id_curso) if id_curso.isdigit() else 2

    # Ejecutar procesamiento
    procesador = ProcesadorIntegrado()
    procesador.ejecutar_flujo_completo(id_curso)


if __name__ == "__main__":
    main()
