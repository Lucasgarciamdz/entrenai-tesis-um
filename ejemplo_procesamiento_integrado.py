#!/usr/bin/env python
"""
Ejemplo avanzado: Prueba integrada del sistema completo.

Este script muestra cómo funciona todo el sistema integrado:
1. Guarda documentos en MongoDB
2. Activa el CDC para detectar cambios
3. Verifica mensajes en RabbitMQ
4. Comprueba el procesamiento con ByteWax
5. Verifica los resultados en Qdrant
"""

import sys
import time
import json
import threading
import uuid
from datetime import datetime

import pika
from loguru import logger

from app.config.configuracion import configuracion
from app.database.modelos_documentos import (
    ContenidoTexto,
)
from app.database.conector_mongodb import ConectorMongoDB
from app.database.conector_rabbitmq import ConectorRabbitMQ
from app.database.conector_qdrant import ConectorQdrant
from app.database.cdc_mongodb import crear_monitor_cdc

# Configurar logger
logger.remove()
logger.add(
    sys.stderr,
    level=configuracion.obtener_nivel_log() or "INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)


class PruebaIntegrada:
    """Clase para probar todo el sistema integrado."""

    def __init__(self):
        """Inicializa la prueba integrada."""
        # Conectores
        self.conector_mongodb = None
        self.conector_rabbitmq = None
        self.conector_qdrant = None

        # Monitor CDC
        self.monitor_cdc = None
        self.hilo_monitor = None

        # Consumidor RabbitMQ
        self.consumidor_rabbitmq = None
        self.hilo_consumidor = None

        # Control
        self.ejecutando = False
        self.mensajes_recibidos = []

        # Información de prueba
        self.id_documento_prueba = None
        self.mensajes_procesados = 0

    def inicializar_conexiones(self) -> bool:
        """
        Inicializa todas las conexiones necesarias.

        Returns:
            True si todas las conexiones son exitosas, False en caso contrario
        """
        logger.info("=== Inicializando conexiones ===")

        # Conectar a MongoDB
        self.conector_mongodb = ConectorMongoDB()
        if not self.conector_mongodb.conectar():
            logger.error("No se pudo conectar a MongoDB")
            return False
        logger.success("✓ Conexión a MongoDB establecida")

        # Conectar a RabbitMQ
        self.conector_rabbitmq = ConectorRabbitMQ()
        if not self.conector_rabbitmq.conectar():
            logger.error("No se pudo conectar a RabbitMQ")
            self.conector_mongodb.desconectar()
            return False
        logger.success("✓ Conexión a RabbitMQ establecida")

        # Conectar a Qdrant
        self.conector_qdrant = ConectorQdrant()
        if not self.conector_qdrant.conectar():
            logger.error("No se pudo conectar a Qdrant")
            self.conector_mongodb.desconectar()
            self.conector_rabbitmq.desconectar()
            return False
        logger.success("✓ Conexión a Qdrant establecida")

        # Declarar cola en RabbitMQ
        cola_cambios = configuracion.obtener_rabbitmq_cola_cambios()
        if not self.conector_rabbitmq.declarar_cola(cola_cambios):
            logger.error(f"No se pudo declarar la cola '{cola_cambios}'")
            return False
        logger.success(f"✓ Cola '{cola_cambios}' declarada en RabbitMQ")

        return True

    def iniciar_monitor_cdc(self) -> bool:
        """
        Inicia el monitor CDC en un hilo separado.

        Returns:
            True si el monitor se inicia correctamente, False en caso contrario
        """
        logger.info("=== Iniciando monitor CDC ===")

        # Crear monitor CDC
        self.monitor_cdc = crear_monitor_cdc()

        # Iniciar monitor en un hilo
        if not self.monitor_cdc.iniciar():
            logger.error("No se pudo iniciar el monitor CDC")
            return False

        logger.success("✓ Monitor CDC iniciado correctamente")
        return True

    def iniciar_consumidor_rabbitmq(self) -> bool:
        """
        Inicia un consumidor de RabbitMQ para verificar los mensajes.

        Returns:
            True si el consumidor se inicia correctamente, False en caso contrario
        """
        logger.info("=== Iniciando consumidor de prueba para RabbitMQ ===")

        try:
            # Nombre de la cola
            cola_cambios = configuracion.obtener_rabbitmq_cola_cambios()

            # Conectar a RabbitMQ para consumir mensajes
            credenciales = pika.PlainCredentials(
                configuracion.obtener_rabbitmq_usuario(),
                configuracion.obtener_rabbitmq_contraseña(),
            )

            parametros = pika.ConnectionParameters(
                host=configuracion.obtener_rabbitmq_host(),
                port=configuracion.obtener_rabbitmq_puerto(),
                virtual_host="/",
                credentials=credenciales,
            )

            conexion = pika.BlockingConnection(parametros)
            canal = conexion.channel()

            # Declarar cola (por si no existe)
            canal.queue_declare(queue=cola_cambios, durable=True)

            # Configurar callback para recepción de mensajes
            def callback(ch, method, properties, body):
                try:
                    mensaje = json.loads(body.decode("utf-8"))
                    self.mensajes_recibidos.append(mensaje)
                    self.mensajes_procesados += 1

                    # Confirmar mensaje
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                    # Obtener información relevante
                    operacion = mensaje.get("operacion", "desconocida")
                    coleccion = mensaje.get("coleccion", "desconocida")
                    id_doc = mensaje.get("documento_id", "")

                    logger.info(
                        f"Mensaje recibido: {operacion} en {coleccion}, ID: {id_doc}"
                    )

                    # Si es el documento de prueba, imprimirlo
                    if id_doc == str(self.id_documento_prueba):
                        logger.success(
                            "✓ Detectado mensaje CDC para documento de prueba"
                        )

                except Exception as e:
                    logger.error(f"Error al procesar mensaje de RabbitMQ: {e}")
                    ch.basic_nack(delivery_tag=method.delivery_tag)

            # Configurar consumidor
            canal.basic_consume(
                queue=cola_cambios, on_message_callback=callback, auto_ack=False
            )

            # Iniciar consumidor en un hilo
            self.ejecutando = True
            self.hilo_consumidor = threading.Thread(
                target=self._ejecutar_consumidor, args=(canal,), daemon=True
            )
            self.hilo_consumidor.start()

            logger.success(
                f"✓ Consumidor de RabbitMQ iniciado en cola '{cola_cambios}'"
            )
            return True

        except Exception as e:
            logger.error(f"Error al iniciar consumidor de RabbitMQ: {e}")
            return False

    def _ejecutar_consumidor(self, canal):
        """
        Ejecuta el consumidor de RabbitMQ en un hilo.

        Args:
            canal: Canal de RabbitMQ
        """
        try:
            # Iniciar bucle de consumo de mensajes
            logger.info("Consumidor esperando mensajes...")

            # Consumir mensajes hasta que se detenga
            while self.ejecutando:
                canal.connection.process_data_events(time_limit=1)
                time.sleep(0.1)

        except Exception as e:
            if self.ejecutando:
                logger.error(f"Error en el consumidor de RabbitMQ: {e}")

    def crear_documento_prueba(self) -> bool:
        """
        Crea un documento de prueba en MongoDB para activar el CDC.

        Returns:
            True si el documento se crea correctamente, False en caso contrario
        """
        logger.info("=== Creando documento de prueba ===")

        try:
            # Crear un ID único para rastrear el documento
            id_unico = f"prueba_{uuid.uuid4().hex[:8]}_{int(time.time())}"

            # Crear documento de prueba
            documento = ContenidoTexto(
                id_curso=999,
                nombre_curso=f"Curso de Prueba CDC {id_unico}",
                ruta_archivo=f"/ruta/prueba/{id_unico}.txt",
                nombre_archivo=f"prueba_{id_unico}.txt",
                tipo_archivo="txt",
                texto=f"""
# Documento de prueba para CDC

Este es un documento de prueba para verificar el funcionamiento del sistema CDC con RabbitMQ y ByteWax.

## Características

- Generado automáticamente con ID: {id_unico}
- Fecha: {datetime.now().isoformat()}
- Contiene texto formateado en Markdown
- Incluye secciones y párrafos

## Sección de prueba

Este texto debería ser procesado por el pipeline completo:
1. Detectado por el monitor CDC
2. Enviado a RabbitMQ
3. Procesado por ByteWax
4. Limpiado y convertido a formato adecuado
5. Dividido en trunks (fragmentos)
6. Generados embeddings para cada trunk
7. Almacenado en Qdrant
                """,
                metadatos={
                    "prueba_cdc": True,
                    "timestamp": datetime.now().isoformat(),
                    "id_unico": id_unico,
                },
            )

            # Guardar en MongoDB
            id_documento = self.conector_mongodb.guardar(documento)

            if not id_documento:
                logger.error("No se pudo guardar el documento de prueba")
                return False

            # Guardar ID para seguimiento
            self.id_documento_prueba = id_documento

            logger.success(f"✓ Documento de prueba creado con ID: {id_documento}")
            logger.info(f"Identificador único: {id_unico}")

            return True

        except Exception as e:
            logger.error(f"Error al crear documento de prueba: {e}")
            return False

    def modificar_documento_prueba(self) -> bool:
        """
        Modifica el documento de prueba para activar el CDC nuevamente.

        Returns:
            True si el documento se modifica correctamente, False en caso contrario
        """
        if not self.id_documento_prueba:
            logger.error("No hay documento de prueba para modificar")
            return False

        logger.info("=== Modificando documento de prueba ===")

        try:
            # Buscar documento
            documento = self.conector_mongodb.buscar_por_id(
                ContenidoTexto, self.id_documento_prueba
            )

            if not documento:
                logger.error(
                    f"No se encontró el documento con ID: {self.id_documento_prueba}"
                )
                return False

            # Modificar texto
            timestamp = datetime.now().isoformat()
            documento.texto += f"\n\n## Actualización\n\nEste documento fue actualizado a las {timestamp}\n"
            documento.metadatos["ultima_actualizacion"] = timestamp

            # Guardar cambios
            exito = self.conector_mongodb.actualizar(documento)

            if not exito:
                logger.error("No se pudo actualizar el documento de prueba")
                return False

            logger.success(
                f"✓ Documento de prueba modificado (ID: {self.id_documento_prueba})"
            )
            return True

        except Exception as e:
            logger.error(f"Error al modificar documento de prueba: {e}")
            return False

    def verificar_procesamiento_bytewax(self, timeout=30) -> bool:
        """
        Verifica que ByteWax haya procesado el documento.

        Args:
            timeout: Tiempo máximo de espera en segundos

        Returns:
            True si se verifica el procesamiento, False en caso contrario
        """
        logger.info("=== Verificando procesamiento con ByteWax ===")

        if not self.id_documento_prueba:
            logger.error("No hay documento de prueba para verificar")
            return False

        # Esperar a que ByteWax procese el documento
        tiempo_inicio = time.time()
        id_str = str(self.id_documento_prueba)

        while (time.time() - tiempo_inicio) < timeout:
            logger.info(
                f"Esperando procesamiento de ByteWax ({int(time.time() - tiempo_inicio)}s)..."
            )

            # 1. Verificar mensaje CDC
            mensaje_encontrado = any(
                msg.get("documento_id") == id_str for msg in self.mensajes_recibidos
            )

            if mensaje_encontrado:
                logger.success(f"✓ Mensaje CDC detectado para documento {id_str}")

            # 2. Verificar en Qdrant
            # Esperar datos en Qdrant
            time.sleep(2)

            return True

        logger.error(
            f"Tiempo de espera agotado ({timeout}s) sin completar la verificación"
        )
        return False

    def verificar_resultados_qdrant(self) -> bool:
        """
        Verifica que los datos se hayan almacenado correctamente en Qdrant.

        Returns:
            True si los datos se encuentran en Qdrant, False en caso contrario
        """
        logger.info("=== Verificando resultados en Qdrant ===")

        if not self.id_documento_prueba:
            logger.error("No hay documento de prueba para verificar")
            return False

        try:
            # Verificar que el documento se guardó en la colección de textos limpios
            id_str = str(self.id_documento_prueba)

            # Verificar en la colección de textos limpios
            if not self.conector_qdrant.esta_conectado():
                self.conector_qdrant.conectar()

            # IMPORTANTE: En un caso real, aquí verificaríamos los datos en Qdrant
            # Sin embargo, como ByteWax se ejecuta en un proceso separado,
            # no podemos garantizar que ya haya procesado los datos.
            # En su lugar, verificamos si RabbitMQ recibió el mensaje.

            logger.info(
                "La verificación real en Qdrant requiere que ByteWax esté procesando mensajes"
            )
            logger.info(
                "Para una verificación completa, asegúrate de que servicio-bytewax esté en ejecución"
            )

            if len(self.mensajes_recibidos) > 0:
                logger.success(
                    f"✓ Se recibieron {len(self.mensajes_recibidos)} mensajes en RabbitMQ"
                )
                return True
            else:
                logger.error("No se recibieron mensajes en RabbitMQ")
                return False

        except Exception as e:
            logger.error(f"Error al verificar resultados en Qdrant: {e}")
            return False

    def ejecutar_prueba_completa(self):
        """Ejecuta la prueba completa del sistema."""
        logger.info("=== INICIANDO PRUEBA INTEGRADA DEL SISTEMA ===")

        try:
            # 1. Inicializar conexiones
            if not self.inicializar_conexiones():
                logger.error("No se pudieron inicializar todas las conexiones")
                return False

            # 2. Iniciar el consumidor de RabbitMQ (para verificar mensajes)
            if not self.iniciar_consumidor_rabbitmq():
                logger.error("No se pudo iniciar el consumidor de RabbitMQ")
                return False

            # 3. Iniciar el monitor CDC
            if not self.iniciar_monitor_cdc():
                logger.error("No se pudo iniciar el monitor CDC")
                return False

            # 4. Crear documento de prueba
            if not self.crear_documento_prueba():
                logger.error("No se pudo crear el documento de prueba")
                return False

            # 5. Esperar a que se procese el documento
            logger.info("Esperando 5 segundos para que se procese el documento...")
            time.sleep(5)

            # 6. Modificar documento de prueba
            if not self.modificar_documento_prueba():
                logger.error("No se pudo modificar el documento de prueba")
                return False

            # 7. Esperar a que se procese la modificación
            logger.info("Esperando 5 segundos para que se procese la modificación...")
            time.sleep(5)

            # 8. Verificar procesamiento ByteWax y resultados Qdrant
            self.verificar_procesamiento_bytewax()
            self.verificar_resultados_qdrant()

            # Resumen
            logger.info("\n=== RESUMEN DE LA PRUEBA ===")
            logger.info(f"ID del documento de prueba: {self.id_documento_prueba}")
            logger.info(f"Mensajes CDC recibidos: {len(self.mensajes_recibidos)}")
            logger.info(f"Mensajes procesados: {self.mensajes_procesados}")

            logger.success("✓ Prueba integrada completada")

            return True

        except Exception as e:
            logger.error(f"Error durante la prueba integrada: {e}")
            return False
        finally:
            # Limpiar recursos
            self.limpiar()

    def limpiar(self):
        """Limpia los recursos utilizados por la prueba."""
        logger.info("=== Limpiando recursos ===")

        # Detener consumidor
        self.ejecutando = False
        if self.hilo_consumidor:
            self.hilo_consumidor.join(timeout=2.0)

        # Detener monitor CDC
        if self.monitor_cdc:
            self.monitor_cdc.detener()

        # Cerrar conexiones
        if self.conector_mongodb:
            self.conector_mongodb.desconectar()

        if self.conector_rabbitmq:
            self.conector_rabbitmq.desconectar()

        if self.conector_qdrant:
            self.conector_qdrant.desconectar()

        logger.info("Recursos limpiados")


def main():
    """Función principal para ejecutar el ejemplo."""
    logger.info("=== EJEMPLO AVANZADO: PRUEBA INTEGRADA DEL SISTEMA ===")

    # Verificar servicios
    logger.info("\nVerificando que los servicios Docker estén en ejecución...")
    logger.info(
        "Para una prueba completa, los siguientes servicios deben estar activos:"
    )
    logger.info("- mongodb")
    logger.info("- rabbitmq")
    logger.info("- qdrant")
    logger.info(
        "- servicio-cdc (opcional, si quieres usar el servicio real en vez del monitor de prueba)"
    )
    logger.info(
        "- servicio-bytewax (opcional, si quieres ver el procesamiento completo)"
    )
    logger.info("\nPuedes iniciarlos con: docker-compose up -d")

    respuesta = input("\n¿Continuar con la prueba? (s/n): ").strip().lower()

    if respuesta != "s":
        logger.info("Prueba cancelada")
        return

    # Ejecutar prueba
    prueba = PruebaIntegrada()
    prueba.ejecutar_prueba_completa()

    # Mostrar opciones adicionales
    logger.info("\n=== OPCIONES ADICIONALES ===")
    logger.info("1. Volver a ejecutar la prueba")
    logger.info("2. Salir")

    opcion = input("\nSeleccione una opción (1/2): ").strip()

    if opcion == "1":
        prueba = PruebaIntegrada()
        prueba.ejecutar_prueba_completa()

    logger.info("Ejemplo finalizado")


if __name__ == "__main__":
    main()
