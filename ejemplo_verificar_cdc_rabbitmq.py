#!/usr/bin/env python
"""
Ejemplo de verificación de CDC: Comprobar la integración entre MongoDB y RabbitMQ.

Este script simplificado verifica que el sistema CDC (Change Data Capture)
está funcionando correctamente, detectando cambios en MongoDB y enviándolos a RabbitMQ.
"""

import sys
import time
import json
import threading

from loguru import logger

from app.config.configuracion import configuracion
from app.database.conector_mongodb import ConectorMongoDB
from app.database.conector_rabbitmq import ConectorRabbitMQ
from app.database.modelos_documentos import ContenidoTexto


# Configurar logger
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>[{time:HH:mm:ss}]</green> <level>{level}</level> | {message}",
)


class VerificadorCDC:
    """Clase simplificada para verificar la integración CDC entre MongoDB y RabbitMQ."""

    def __init__(self):
        """Inicializa el verificador."""
        self.mensajes_recibidos = []
        self.detener_evento = threading.Event()

        # Configurar conexiones
        mongo_host = configuracion.obtener_mongodb_host()
        mongo_puerto = configuracion.obtener_mongodb_puerto()
        mongo_usuario = configuracion.obtener_mongodb_usuario()
        mongo_password = configuracion.obtener_mongodb_contraseña()
        mongo_db = configuracion.obtener_mongodb_base_datos()

        rabbitmq_host = configuracion.obtener_rabbitmq_host()
        rabbitmq_puerto = configuracion.obtener_rabbitmq_puerto()
        rabbitmq_usuario = configuracion.obtener_rabbitmq_usuario()
        rabbitmq_password = configuracion.obtener_rabbitmq_contraseña()
        self.cola_cambios = configuracion.obtener_rabbitmq_cola_cambios()

        # Inicializar conectores
        self.mongodb = ConectorMongoDB(
            host=mongo_host,
            puerto=mongo_puerto,
            usuario=mongo_usuario,
            contraseña=mongo_password,
            base_datos=mongo_db,
        )

        self.rabbitmq = ConectorRabbitMQ(
            host=rabbitmq_host,
            puerto=rabbitmq_puerto,
            usuario=rabbitmq_usuario,
            contraseña=rabbitmq_password,
        )

        self.monitor_cdc = None
        self.hilo_consumidor = None
        self.canal_consumidor = None

    def iniciar_consumidor(self):
        """Inicia un consumidor de mensajes RabbitMQ."""
        if not self.rabbitmq.esta_conectado():
            if not self.rabbitmq.conectar():
                logger.error("No se pudo conectar a RabbitMQ")
                return False

        # Declarar cola
        if not self.rabbitmq.declarar_cola(self.cola_cambios):
            logger.error(f"No se pudo declarar la cola {self.cola_cambios}")
            return False

        # Definir callback para procesar mensajes
        def callback(ch, method, properties, body):
            try:
                mensaje = json.loads(body.decode("utf-8"))
                self.mensajes_recibidos.append(mensaje)

                # Extraer información básica para mostrar
                op_type = mensaje.get("operationType", "desconocida")
                collection = mensaje.get("ns", {}).get("coll", "desconocida")
                doc_id = str(mensaje.get("documentKey", {}).get("_id", ""))

                logger.info(
                    f"CDC: Recibido mensaje {op_type} en {collection}, ID: {doc_id}"
                )

                # Confirmar procesamiento
                ch.basic_ack(delivery_tag=method.delivery_tag)

            except Exception as e:
                logger.error(f"Error procesando mensaje: {e}")
                # Intentar rechazar el mensaje sin fallar
                try:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                except Exception as nack_error:
                    logger.error(f"Error al rechazar mensaje: {nack_error}")

        try:
            # Crear un nuevo canal para consumidor
            # No reutilizar el canal principal del conector para evitar conflictos
            if hasattr(self, "canal_consumidor") and self.canal_consumidor is not None:
                try:
                    self.canal_consumidor.close()
                except Exception:
                    pass

            # Crear canal
            self.canal_consumidor = self.rabbitmq.conexion.channel()
            self.canal_consumidor.basic_qos(prefetch_count=1)

            # Configurar consumidor
            self.canal_consumidor.basic_consume(
                queue=self.cola_cambios, on_message_callback=callback, auto_ack=False
            )

            # Iniciar consumidor en thread separado
            def consumir():
                try:
                    logger.info("Consumidor RabbitMQ iniciado")
                    while not self.detener_evento.is_set():
                        try:
                            # Procesar un mensaje o timeout
                            # Usar un timeout más corto para reaccionar más rápido a errores
                            self.canal_consumidor.connection.process_data_events(
                                time_limit=0.2
                            )
                        except Exception as e:
                            if not self.detener_evento.is_set():
                                logger.error(f"Error en process_data_events: {e}")
                                # Si hay error, poner a dormir el hilo para no saturar logs
                                time.sleep(0.5)
                                try:
                                    # Intentar reconectar solo si no estamos deteniendo
                                    if not self.detener_evento.is_set() and (
                                        not self.rabbitmq.esta_conectado()
                                        or not self.canal_consumidor
                                        or not self.canal_consumidor.is_open
                                    ):
                                        logger.info(
                                            "Intentando reconectar consumidor RabbitMQ..."
                                        )
                                        self.rabbitmq.conectar()
                                        # Usamos return para que el hilo actual termine
                                        # y la función iniciar_consumidor cree uno nuevo
                                        return
                                except Exception as reconnect_err:
                                    logger.error(
                                        f"Error intentando reconectar: {reconnect_err}"
                                    )
                except Exception as e:
                    logger.error(f"Error en hilo consumidor: {e}")
                finally:
                    logger.debug("Hilo consumidor finalizado")

            # Terminar correctamente hilo anterior si existe
            if self.hilo_consumidor and self.hilo_consumidor.is_alive():
                self.detener_evento.set()
                # No intentamos join en el hilo actual
                if threading.current_thread() is not self.hilo_consumidor:
                    self.hilo_consumidor.join(timeout=2.0)
                self.detener_evento.clear()

            # Iniciar nuevo hilo consumidor
            self.hilo_consumidor = threading.Thread(target=consumir, daemon=True)
            self.hilo_consumidor.start()

            return True
        except Exception as e:
            logger.error(f"Error al iniciar consumidor: {e}")
            return False

    def iniciar_monitor_cdc(self):
        """Inicia el monitor CDC para detectar cambios en MongoDB."""
        from app.database.cdc_mongodb import crear_monitor_cdc

        # Obtener credenciales de MongoDB
        mongo_host = configuracion.obtener_mongodb_host()
        mongo_puerto = configuracion.obtener_mongodb_puerto()
        mongo_usuario = configuracion.obtener_mongodb_usuario()
        mongo_password = configuracion.obtener_mongodb_contraseña()
        mongo_db = configuracion.obtener_mongodb_base_datos()

        # Iniciar monitor
        self.monitor_cdc = crear_monitor_cdc(
            host=mongo_host,
            puerto=mongo_puerto,
            usuario=mongo_usuario,
            contraseña=mongo_password,
            base_datos=mongo_db,
            cola=self.cola_cambios,
            colecciones=["recursos"],  # Solo monitoreamos la colección 'recursos'
            filtro_operaciones=["insert", "update", "replace", "delete"],
        )

        logger.info("Monitor CDC iniciado correctamente")

    def insertar_documento_prueba(self):
        """Inserta un documento de prueba en MongoDB."""
        logger.info("Insertando documento de prueba en MongoDB")

        # Crear documento de prueba
        documento = ContenidoTexto(
            id_curso=1,
            nombre_curso="Curso de prueba CDC",
            ruta_archivo="/ruta/ficticia/documento_prueba.txt",
            nombre_archivo="documento_prueba.txt",
            tipo_archivo="txt",
            texto=f"""
            Este es un documento de prueba para verificar el CDC.
            Hora de creación: {time.strftime("%H:%M:%S")}
            """,
            metadatos={"origen": "prueba_cdc"},
        )

        # Guardar en MongoDB
        id_documento = self.mongodb.guardar(documento)

        if id_documento:
            logger.info(f"Documento insertado con ID: {id_documento}")
            return id_documento
        else:
            logger.error("Error al insertar documento")
            return None

    def actualizar_documento(self, id_documento):
        """Actualiza un documento existente."""
        logger.info(f"Actualizando documento {id_documento}")

        # Obtener documento
        documento = self.mongodb.buscar_por_id(ContenidoTexto, id_documento)

        if not documento:
            logger.error(f"Documento no encontrado: {id_documento}")
            return False

        # Actualizar texto
        documento.texto = f"""
        Este documento ha sido actualizado.
        Hora de actualización: {time.strftime("%H:%M:%S")}
        """

        # Guardar cambios
        if self.mongodb.actualizar(documento):
            logger.info(f"Documento actualizado: {id_documento}")
            return True
        else:
            logger.error(f"Error al actualizar documento: {id_documento}")
            return False

    def eliminar_documento(self, id_documento):
        """Elimina un documento."""
        logger.info(f"Eliminando documento {id_documento}")

        # Eliminar documento
        try:
            if self.mongodb.eliminar_recurso(id_documento):
                logger.info(f"Documento eliminado: {id_documento}")
                return True
            else:
                logger.error(f"Error al eliminar documento: {id_documento}")
                return False
        except Exception as e:
            logger.error(f"Excepción al eliminar documento: {e}")
            return False

        logger.info("Recursos limpiados")

    def ejecutar_prueba(self):
        """Ejecuta una prueba completa del sistema CDC."""
        try:
            # 1. Iniciar monitor CDC
            logger.info("Iniciando monitor CDC...")
            self.iniciar_monitor_cdc()

            # 2. Iniciar consumidor RabbitMQ
            logger.info("Iniciando consumidor RabbitMQ...")
            if not self.iniciar_consumidor():
                logger.error("No se pudo iniciar el consumidor RabbitMQ")
                return False

            # Esperar a que el monitor CDC esté listo
            logger.info("Esperando a que el monitor CDC esté listo...")
            time.sleep(3)

            # 3. Insertar documento
            id_documento = self.insertar_documento_prueba()
            if not id_documento:
                raise Exception("No se pudo insertar documento de prueba")

            # 4. Actualizar documento
            self.actualizar_documento(id_documento)

            # 5. Eliminar documento
            self.eliminar_documento(id_documento)

            # 6. Esperar mensajes CDC (debemos recibir 3 mensajes: insert, update, delete)
            logger.info("Esperando mensajes CDC (timeout: 20 segundos)...")

            # Esperar hasta 20 segundos para recibir 3 mensajes
            inicio = time.time()
            while (time.time() - inicio) < 20:
                time.sleep(2)

                # Verificar si hemos recibido los 3 mensajes
                mensajes = len(self.mensajes_recibidos)
                logger.info(f"Mensajes recibidos hasta ahora: {mensajes}")

                if mensajes >= 3:
                    break

            # 7. Mostrar resultados
            total_mensajes = len(self.mensajes_recibidos)
            logger.info(f"\nResultados: {total_mensajes} mensajes CDC recibidos")

            if total_mensajes == 0:
                logger.error("❌ No se recibieron mensajes CDC")
                return False

            # Contar operaciones
            operaciones = {}
            for mensaje in self.mensajes_recibidos:
                op = mensaje.get("operationType", "desconocida")
                operaciones[op] = operaciones.get(op, 0) + 1

            # Mostrar operaciones
            logger.info("Operaciones recibidas:")
            for op, count in operaciones.items():
                logger.info(f"  - {op}: {count}")

            # Verificar si recibimos todos los tipos de operaciones
            exito = (
                "insert" in operaciones
                and "update" in operaciones
                and "delete" in operaciones
            )

            if exito:
                logger.info("✅ CDC funcionando correctamente")
            else:
                logger.warning("⚠️ CDC funcionando parcialmente")

            return exito

        except Exception as e:
            logger.error(f"Error durante la prueba: {e}")
            return False


def verificar_servicios():
    """Verifica que los servicios necesarios estén en ejecución."""
    try:
        # Verificar MongoDB
        from pymongo import MongoClient

        mongo_host = configuracion.obtener_mongodb_host()
        mongo_puerto = configuracion.obtener_mongodb_puerto()
        mongo_usuario = configuracion.obtener_mongodb_usuario()
        mongo_password = configuracion.obtener_mongodb_contraseña()

        if mongo_usuario and mongo_password:
            uri = f"mongodb://{mongo_usuario}:{mongo_password}@{mongo_host}:{mongo_puerto}/"
        else:
            uri = f"mongodb://{mongo_host}:{mongo_puerto}/"

        cliente = MongoClient(uri, serverSelectionTimeoutMS=5000)
        cliente.admin.command("ping")
        cliente.close()

        logger.info(f"✅ MongoDB disponible en {mongo_host}:{mongo_puerto}")

        # Verificar RabbitMQ
        import pika

        rabbit_host = configuracion.obtener_rabbitmq_host()
        rabbit_puerto = configuracion.obtener_rabbitmq_puerto()
        rabbit_usuario = configuracion.obtener_rabbitmq_usuario()
        rabbit_password = configuracion.obtener_rabbitmq_contraseña()

        credentials = (
            pika.PlainCredentials(rabbit_usuario, rabbit_password)
            if rabbit_usuario and rabbit_password
            else None
        )
        parameters = pika.ConnectionParameters(
            host=rabbit_host,
            port=rabbit_puerto,
            credentials=credentials,
            connection_attempts=1,
            socket_timeout=3,
        )

        connection = pika.BlockingConnection(parameters)
        connection.close()

        logger.info(f"✅ RabbitMQ disponible en {rabbit_host}:{rabbit_puerto}")

        return True

    except Exception as e:
        logger.error(f"Error al verificar servicios: {e}")
        return False


def main():
    """Función principal."""
    logger.info("VERIFICADOR SIMPLE DE CDC MONGODB-RABBITMQ")
    logger.info("==========================================")

    # Verificar servicios
    if not verificar_servicios():
        logger.error("No se puede continuar sin los servicios necesarios")
        logger.error(
            "Por favor, asegúrese de que MongoDB y RabbitMQ estén en ejecución"
        )
        logger.error("Ejecute: docker-compose up -d mongodb rabbitmq")
        return

    # Ejecutar verificación
    verificador = VerificadorCDC()
    try:
        if verificador.ejecutar_prueba():
            logger.info("✅ Verificación exitosa: CDC está funcionando correctamente")
        else:
            logger.error(
                "❌ Verificación fallida: CDC no está funcionando correctamente"
            )
    except Exception as e:
        logger.error(f"Error durante la verificación: {e}")


if __name__ == "__main__":
    main()
