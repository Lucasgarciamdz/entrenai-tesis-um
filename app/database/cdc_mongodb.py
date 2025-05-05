"""
Módulo de Change Data Capture (CDC) para MongoDB.

Este módulo implementa un patrón similar a CDC para capturar cambios en MongoDB
y publicarlos en una cola de RabbitMQ. La implementación funciona tanto con MongoDB
en modo standalone como con replica sets.
"""

import json
import threading
import time
from typing import Dict, Any, List, Optional

from pymongo.collection import Collection
from bson import json_util

from loguru import logger
from .conector_mongodb import ConectorMongoDB
from .conector_rabbitmq import ConectorRabbitMQ


class MonitorCambiosMongoDB:
    """
    Monitor de Change Data Capture (CDC) para MongoDB.

    Esta clase se encarga de monitorear los cambios en MongoDB y publicarlos
    en una cola de RabbitMQ. Soporta tanto changeStreams (para clusters con
    replica sets) como polling (para instancias standalone).
    """

    def __init__(
        self,
        host: str,
        puerto: int,
        usuario: str,
        contraseña: str,
        base_datos: str,
        cola: str,
        colecciones: Optional[List[str]] = None,
        filtro_operaciones: Optional[List[str]] = None,
        intervalo_polling: int = 5,
    ):
        """
        Inicializa el monitor de cambios.

        Args:
            host: Host de MongoDB
            puerto: Puerto de MongoDB
            usuario: Usuario de MongoDB
            contraseña: Contraseña de MongoDB
            base_datos: Nombre de la base de datos a monitorear
            cola: Nombre de la cola de RabbitMQ donde publicar los cambios
            colecciones: Lista de colecciones a monitorear (todas si es None)
            filtro_operaciones: Lista de operaciones a monitorear (todas si es None)
            intervalo_polling: Intervalo en segundos para el polling
        """
        # Configuración de MongoDB
        self.host = host
        self.puerto = puerto
        self.usuario = usuario
        self.contraseña = contraseña
        self.base_datos = base_datos

        # Configuración de monitoreo
        self.nombre_cola = cola
        self.colecciones = colecciones
        self.filtro_operaciones = filtro_operaciones or [
            "insert",
            "update",
            "delete",
            "replace",
        ]
        self.intervalo_polling = intervalo_polling

        # Estado de ejecución
        self.ejecutando = False
        self.hilo_monitor = None
        self.ultimo_heartbeat = 0

        # Conexiones
        self.conector_mongodb = None
        self.conector_rabbitmq = None

        # Estado para polling
        self.ultimo_estado = {}

    def iniciar(self) -> bool:
        """
        Inicia el monitor de cambios en un hilo separado.

        Returns:
            True si el monitor se inició correctamente.
        """
        if self.ejecutando:
            logger.warning("El monitor ya está en ejecución")
            return True

        # Conectar a MongoDB
        self.conector_mongodb = ConectorMongoDB(
            host=self.host,
            puerto=self.puerto,
            usuario=self.usuario,
            contraseña=self.contraseña,
            base_datos=self.base_datos,
        )

        if not self.conector_mongodb.conectar():
            logger.error("No se pudo conectar a MongoDB")
            return False

        # Conectar a RabbitMQ
        self.conector_rabbitmq = ConectorRabbitMQ()
        if not self.conector_rabbitmq.conectar():
            logger.error("No se pudo conectar a RabbitMQ")
            self.conector_mongodb.desconectar()
            return False

        # Declarar cola para mensajes
        self.conector_rabbitmq.declarar_cola(self.nombre_cola)

        # Iniciar monitoreo en un hilo
        self.ejecutando = True
        self.ultimo_heartbeat = time.time()
        self.hilo_monitor = threading.Thread(target=self._ejecutar_monitor)
        self.hilo_monitor.daemon = True
        self.hilo_monitor.start()

        logger.info(f"Monitor de cambios iniciado para la cola '{self.nombre_cola}'")
        return True

    def detener(self):
        """Detiene el monitor de cambios."""
        self.ejecutando = False

        if self.hilo_monitor and self.hilo_monitor.is_alive():
            self.hilo_monitor.join(timeout=5.0)

        # Cerrar conexiones
        if self.conector_mongodb:
            self.conector_mongodb.desconectar()

        logger.info("Monitor de cambios detenido")
        
    def esta_ejecutando(self) -> bool:
        """
        Verifica si el monitor está activo.
        
        Returns:
            True si el monitor está en ejecución y actualizado, False en caso contrario.
        """
        # Verificar si el hilo existe y está vivo
        if not self.hilo_monitor or not self.hilo_monitor.is_alive():
            return False
            
        # Verificar si el heartbeat está actualizado (no más de 30 segundos de antigüedad)
        if time.time() - self.ultimo_heartbeat > 30:
            logger.warning(f"El monitor CDC no ha reportado actividad en más de 30 segundos")
            return False
            
        return self.ejecutando

    def _ejecutar_monitor(self):
        """Ejecuta el monitoreo de cambios."""
        try:
            db = self.conector_mongodb.db

            # Crear pipeline para filtrar operaciones
            pipeline = self._crear_pipeline_filtro() if self.filtro_operaciones else []

            # Intentar usar change streams (solo funciona con replica sets)
            try:
                # Intentar monitorear toda la base de datos o colecciones específicas
                if self.colecciones:
                    coleccion = db[self.colecciones[0]]
                    self._monitorear_coleccion(coleccion, pipeline)
                else:
                    self._monitorear_base_datos(db, pipeline)

            except Exception as e:
                # Si falla, usar polling como alternativa
                logger.warning(
                    f"Change streams no disponibles, usando polling: {str(e)}"
                )
                self._monitorear_por_polling(db)

        except Exception as e:
            logger.error(f"Error en el monitor de cambios: {e}")
        finally:
            self.ejecutando = False

    def _crear_pipeline_filtro(self) -> List[Dict[str, Any]]:
        """
        Crea un pipeline de agregación para filtrar operaciones.

        Returns:
            Pipeline de agregación para filtrar operaciones
        """
        return [{"$match": {"operationType": {"$in": self.filtro_operaciones}}}]

    def _monitorear_base_datos(self, db, pipeline):
        """
        Monitorea cambios en toda la base de datos.

        Args:
            db: Objeto de base de datos
            pipeline: Pipeline de agregación para filtrar cambios
        """
        with db.watch(
            pipeline=pipeline,
            full_document="updateLookup",
        ) as stream:
            # Procesar cada cambio
            for cambio in stream:
                self.ultimo_heartbeat = time.time()
                if not self.ejecutando:
                    break

                self._procesar_cambio(cambio)

    def _monitorear_coleccion(self, coleccion: Collection, pipeline):
        """
        Monitorea cambios en una colección específica.

        Args:
            coleccion: Objeto de colección
            pipeline: Pipeline de agregación para filtrar cambios
        """
        with coleccion.watch(
            pipeline=pipeline,
            full_document="updateLookup",
        ) as stream:
            # Procesar cada cambio
            for cambio in stream:
                self.ultimo_heartbeat = time.time()
                if not self.ejecutando:
                    break

                self._procesar_cambio(cambio)

    def _monitorear_por_polling(self, db):
        """
        Monitorea cambios utilizando polling periódico.

        Args:
            db: Objeto de base de datos MongoDB
        """
        # Determinar colecciones a monitorear
        colecciones_a_monitorear = self.colecciones or db.list_collection_names()
        logger.info(f"Monitoreando colecciones: {', '.join(colecciones_a_monitorear)}")

        # Inicializar el estado anterior
        for coleccion_nombre in colecciones_a_monitorear:
            self.ultimo_estado[coleccion_nombre] = {}
            try:
                # Cargar estado inicial
                for doc in db[coleccion_nombre].find():
                    doc_id = str(doc.get("_id"))
                    # Convertir ObjectId a str para comparaciones
                    doc_copia = self._normalizar_documento(doc)
                    self.ultimo_estado[coleccion_nombre][doc_id] = doc_copia
            except Exception as e:
                logger.error(
                    f"Error al inicializar estado para {coleccion_nombre}: {e}"
                )

        # Ciclo principal de polling
        while self.ejecutando:
            try:
                # Actualizar heartbeat
                self.ultimo_heartbeat = time.time()
                
                # Verificar cada colección
                for coleccion_nombre in colecciones_a_monitorear:
                    try:
                        # Obtener documentos actuales
                        documentos_actuales = {}
                        for doc in db[coleccion_nombre].find():
                            doc_id = str(doc.get("_id"))
                            # Normalizar documento para comparación
                            doc_copia = self._normalizar_documento(doc)
                            documentos_actuales[doc_id] = doc_copia

                            # Verificar si es nuevo o actualizado
                            if doc_id not in self.ultimo_estado[coleccion_nombre]:
                                # Documento nuevo (insert)
                                self._enviar_cambio_a_rabbitmq(
                                    {
                                        "operationType": "insert",
                                        "ns": {"db": db.name, "coll": coleccion_nombre},
                                        "documentKey": {"_id": doc_id},
                                        "fullDocument": doc,
                                    }
                                )
                            elif (
                                doc_copia
                                != self.ultimo_estado[coleccion_nombre][doc_id]
                            ):
                                # Documento actualizado (update)
                                self._enviar_cambio_a_rabbitmq(
                                    {
                                        "operationType": "update",
                                        "ns": {"db": db.name, "coll": coleccion_nombre},
                                        "documentKey": {"_id": doc_id},
                                        "fullDocument": doc,
                                    }
                                )

                        # Verificar documentos eliminados
                        for doc_id in list(self.ultimo_estado[coleccion_nombre].keys()):
                            if doc_id not in documentos_actuales:
                                # Documento eliminado (delete)
                                self._enviar_cambio_a_rabbitmq(
                                    {
                                        "operationType": "delete",
                                        "ns": {"db": db.name, "coll": coleccion_nombre},
                                        "documentKey": {"_id": doc_id},
                                    }
                                )

                        # Actualizar estado
                        self.ultimo_estado[coleccion_nombre] = documentos_actuales

                    except Exception as e:
                        logger.debug(
                            f"Error al monitorear la colección {coleccion_nombre}: {e}"
                        )
                        # Intentar reconectar si es necesario
                        if not self.conector_mongodb.esta_conectado():
                            logger.debug("Intentando reconectar a MongoDB...")
                            self.conector_mongodb.conectar()

            except Exception as e:
                logger.error(f"Error durante el polling de MongoDB: {e}")
                # Intentar reconectar
                try:
                    if not self.conector_mongodb.esta_conectado():
                        logger.debug(
                            "Intentando reconectar a MongoDB durante polling..."
                        )
                        self.conector_mongodb.conectar()
                except Exception as reconnect_error:
                    logger.error(f"Error al reconectar a MongoDB: {reconnect_error}")

            # Esperar antes del siguiente ciclo
            time.sleep(self.intervalo_polling)

    def _normalizar_documento(self, doc):
        """
        Normaliza un documento para comparación, convirtiendo ObjectIds a str.

        Args:
            doc: Documento a normalizar

        Returns:
            Documento normalizado
        """
        # Convertir a JSON y volver a cargar para normalizar ObjectIds
        return json.loads(json_util.dumps(doc))

    def _procesar_cambio(self, cambio: Dict[str, Any]):
        """
        Procesa un cambio detectado en la base de datos.

        Args:
            cambio: Información del cambio detectado
        """
        # Obtener información del cambio
        tipo_operacion = cambio.get("operationType")
        coleccion = cambio.get("ns", {}).get("coll", "")
        documento_id = str(cambio.get("documentKey", {}).get("_id", ""))

        # Verificar si la operación está en el filtro
        if tipo_operacion not in self.filtro_operaciones:
            return

        # Enviar cambio a RabbitMQ
        self._enviar_cambio_a_rabbitmq(cambio)

        # Registrar el cambio
        logger.info(f"CDC: {tipo_operacion} en {coleccion}, ID: {documento_id}")

    def _enviar_cambio_a_rabbitmq(self, cambio: Dict[str, Any]):
        """
        Envía un cambio a la cola de RabbitMQ.

        Args:
            cambio: Información del cambio a enviar
        """
        try:
            # Convertir el cambio a un formato serializable
            cambio_serializable = json.loads(json_util.dumps(cambio))

            # Publicar mensaje
            if self.conector_rabbitmq.publicar_mensaje(
                self.nombre_cola, cambio_serializable
            ):
                # Obtener información para el log
                tipo_operacion = cambio.get("operationType")
                coleccion = cambio.get("ns", {}).get("coll", "")
                logger.info(
                    f"Cambio {tipo_operacion} en {coleccion} publicado en cola '{self.nombre_cola}'"
                )
        except Exception as e:
            logger.error(f"Error al publicar cambio en RabbitMQ: {e}")


def crear_monitor_cdc(
    host: str = None,
    puerto: int = None,
    usuario: str = None,
    contraseña: str = None,
    base_datos: str = None,
    cola: str = None,
    colecciones: Optional[List[str]] = None,
    filtro_operaciones: Optional[List[str]] = None,
    intervalo_polling: int = 5,
    nombre_cola: str = None,  # Para compatibilidad con servicios existentes
) -> MonitorCambiosMongoDB:
    """
    Crea e inicia un monitor CDC para MongoDB.

    Args:
        host: Host de MongoDB (default: configuracion.obtener_mongodb_host())
        puerto: Puerto de MongoDB (default: configuracion.obtener_mongodb_puerto())
        usuario: Usuario de MongoDB (default: configuracion.obtener_mongodb_usuario())
        contraseña: Contraseña de MongoDB (default: configuracion.obtener_mongodb_contraseña())
        base_datos: Nombre de la base de datos a monitorear (default: configuracion.obtener_mongodb_base_datos())
        cola: Nombre de la cola de RabbitMQ donde publicar los cambios
        colecciones: Lista de colecciones a monitorear (todas si es None)
        filtro_operaciones: Lista de operaciones a monitorear (todas si es None)
        intervalo_polling: Intervalo en segundos para el polling
        nombre_cola: Nombre alternativo para la cola (mantiene compatibilidad con servicios)

    Returns:
        Monitor CDC iniciado
    """
    from ..config.configuracion import configuracion
    
    # Usar configuración si no se proporcionan valores
    host = host or configuracion.obtener_mongodb_host()
    puerto = puerto or configuracion.obtener_mongodb_puerto()
    usuario = usuario or configuracion.obtener_mongodb_usuario()
    contraseña = contraseña or configuracion.obtener_mongodb_contraseña()
    base_datos = base_datos or configuracion.obtener_mongodb_base_datos()
    
    # Priorizar nombre_cola sobre cola para compatibilidad
    cola_a_usar = nombre_cola or cola or configuracion.obtener_rabbitmq_cola_cambios()

    # Crear monitor
    monitor = MonitorCambiosMongoDB(
        host=host,
        puerto=puerto,
        usuario=usuario,
        contraseña=contraseña,
        base_datos=base_datos,
        cola=cola_a_usar,
        colecciones=colecciones,
        filtro_operaciones=filtro_operaciones,
        intervalo_polling=intervalo_polling,
    )
    
    return monitor
