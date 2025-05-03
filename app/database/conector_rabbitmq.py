"""
Conector para interactuar con RabbitMQ.

Este módulo define la clase ConectorRabbitMQ que proporciona
funcionalidad para publicar mensajes en colas de RabbitMQ.
"""

import json
from typing import Dict, Any
import pika
from pika.exceptions import AMQPConnectionError
import time

from ..config.configuracion import configuracion
from loguru import logger


class ConectorRabbitMQ:
    """
    Conector para interactuar con RabbitMQ.

    Esta clase implementa el patrón singleton para mantener una única
    conexión con RabbitMQ, proporcionando métodos para publicar mensajes
    en colas.
    """

    _instancia = None

    def __new__(cls, *args, **kwargs):
        """Implementación del patrón singleton."""
        if cls._instancia is None:
            cls._instancia = super(ConectorRabbitMQ, cls).__new__(cls)
        return cls._instancia

    def __init__(
        self,
        host: str = None,
        puerto: int = None,
        usuario: str = None,
        contraseña: str = None,
        virtual_host: str = "/",
    ):
        """
        Inicializa el conector de RabbitMQ.

        Args:
            host: Host de RabbitMQ
            puerto: Puerto de RabbitMQ
            usuario: Usuario para autenticarse con RabbitMQ
            contraseña: Contraseña para autenticarse con RabbitMQ
            virtual_host: Virtual host de RabbitMQ
        """
        # Inicializar solo una vez
        if hasattr(self, "inicializado") and self.inicializado:
            return

        # Cargar parámetros desde configuración o variables de entorno
        self.host = host or configuracion.obtener("RABBITMQ_HOST", "localhost")
        self.puerto = puerto or int(configuracion.obtener("RABBITMQ_PORT", "5672"))
        self.usuario = usuario or configuracion.obtener("RABBITMQ_USERNAME", "guest")
        self.contraseña = contraseña or configuracion.obtener(
            "RABBITMQ_PASSWORD", "guest"
        )
        self.virtual_host = virtual_host

        # Estado de la conexión
        self.conexion = None
        self.canal = None
        self.inicializado = True

    def __enter__(self):
        """Permite usar el conector como un gestor de contexto."""
        self.conectar()
        return self

    def __exit__(self, tipo_exc, exc_val, exc_tb):
        """Cierra la conexión al salir del contexto."""
        self.desconectar()

    def conectar(self) -> bool:
        """
        Establece conexión con RabbitMQ.

        Returns:
            True si la conexión es exitosa, False en caso contrario
        """
        if self.esta_conectado():
            return True

        try:
            # Configurar credenciales
            credenciales = pika.PlainCredentials(self.usuario, self.contraseña)

            # Parámetros de conexión
            parametros = pika.ConnectionParameters(
                host=self.host,
                port=self.puerto,
                virtual_host=self.virtual_host,
                credentials=credenciales,
                # Configuración para reintentos
                connection_attempts=3,
                retry_delay=5,
            )

            # Establecer la conexión
            self.conexion = pika.BlockingConnection(parametros)
            self.canal = self.conexion.channel()

            logger.info(f"Conexión exitosa a RabbitMQ en {self.host}:{self.puerto}")
            return True

        except AMQPConnectionError as e:
            logger.error(f"Error al conectar a RabbitMQ: {e}")
            self.conexion = None
            self.canal = None
            return False

    def desconectar(self):
        """Cierra la conexión con RabbitMQ."""
        try:
            if self.conexion is not None and self.conexion.is_open:
                # Primero cerrar cualquier canal abierto para evitar errores de consumidores activos
                if self.canal is not None and self.canal.is_open:
                    try:
                        # Intentar cancelar cualquier consumidor activo
                        self.canal.close()
                    except Exception as e:
                        logger.warning(f"Error al cerrar canal RabbitMQ: {e}")
                    finally:
                        self.canal = None

                # Luego cerrar la conexión
                try:
                    self.conexion.close()
                except Exception as e:
                    logger.warning(f"Error al cerrar conexión RabbitMQ: {e}")
                finally:
                    self.conexion = None

                logger.info("Conexión a RabbitMQ cerrada")
        except Exception as e:
            logger.error(f"Error durante desconexión de RabbitMQ: {e}")
            # Forzar limpieza de referencias
            self.canal = None
            self.conexion = None

    def esta_conectado(self) -> bool:
        """
        Verifica si la conexión con RabbitMQ está activa.

        Returns:
            True si la conexión está activa, False en caso contrario
        """
        return (
            self.conexion is not None
            and self.conexion.is_open
            and self.canal is not None
            and self.canal.is_open
        )

    def declarar_cola(self, nombre_cola: str, durable: bool = True) -> bool:
        """
        Declara una cola en RabbitMQ.

        Args:
            nombre_cola: Nombre de la cola
            durable: Si la cola debe ser durable (persistir a reinicios)

        Returns:
            True si la operación es exitosa, False en caso contrario
        """
        # Si no está conectado, intentar conectar
        if not self.esta_conectado():
            if not self.conectar():
                return False

        try:
            # Crear un nuevo canal si el actual está cerrado
            if self.canal is None or not self.canal.is_open:
                self.canal = self.conexion.channel()

            # Declarar la cola
            self.canal.queue_declare(queue=nombre_cola, durable=durable)
            logger.info(f"Cola '{nombre_cola}' declarada exitosamente")
            return True
        except Exception as e:
            logger.error(f"Error al declarar la cola '{nombre_cola}': {e}")

            # Intentar reconectar si es un error de conexión
            try:
                self.desconectar()  # Cerrar completamente la conexión actual
                time.sleep(1)  # Esperar un momento
                if self.conectar():  # Intentar reconectar
                    # Intentar declarar la cola nuevamente
                    if self.canal is None or not self.canal.is_open:
                        self.canal = self.conexion.channel()
                    self.canal.queue_declare(queue=nombre_cola, durable=durable)
                    logger.info(
                        f"Cola '{nombre_cola}' declarada exitosamente tras reconexión"
                    )
                    return True
            except Exception as reconnect_error:
                logger.error(f"Error al intentar reconexión: {reconnect_error}")

            return False

    def publicar_mensaje(
        self, nombre_cola: str, mensaje: Dict[str, Any], persistente: bool = True
    ) -> bool:
        """
        Publica un mensaje en una cola de RabbitMQ.

        Args:
            nombre_cola: Nombre de la cola
            mensaje: Mensaje a publicar (se convertirá a JSON)
            persistente: Si el mensaje debe ser persistente

        Returns:
            True si la publicación es exitosa, False en caso contrario
        """
        if not self.esta_conectado() and not self.conectar():
            return False

        try:
            # Asegurar que la cola exista
            self.declarar_cola(nombre_cola)

            # Configurar propiedades del mensaje
            propiedades = pika.BasicProperties(
                delivery_mode=2 if persistente else 1,  # 2 = persistente
            )

            # Convertir el mensaje a JSON
            mensaje_json = json.dumps(mensaje)

            # Publicar el mensaje
            self.canal.basic_publish(
                exchange="",
                routing_key=nombre_cola,
                body=mensaje_json,
                properties=propiedades,
            )

            logger.debug(f"Mensaje publicado en cola '{nombre_cola}'")
            return True

        except Exception as e:
            logger.error(f"Error al publicar mensaje en cola '{nombre_cola}': {e}")
            return False


# Crear una instancia global
conector_rabbitmq = ConectorRabbitMQ()
