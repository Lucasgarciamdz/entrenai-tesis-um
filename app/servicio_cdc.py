#!/usr/bin/env python
"""
Servicio de Change Data Capture (CDC) para MongoDB.

Este script inicia un servicio que monitorea cambios en MongoDB y los
publica en una cola de RabbitMQ para su procesamiento por otros servicios.
"""

import os
import sys
import time
import signal
from typing import Optional, List

from loguru import logger
from pymongo.errors import PyMongoError

from app.config.configuracion import configuracion
from app.database.cdc_mongodb import crear_monitor_cdc, MonitorCambiosMongoDB


class ServicioCDC:
    """
    Servicio principal de CDC.

    Esta clase encapsula la lógica del servicio CDC que monitorea
    cambios en MongoDB y los publica en RabbitMQ.
    """

    def __init__(
        self,
        nombre_cola: Optional[str] = None,
        colecciones: Optional[List[str]] = None,
        filtro_operaciones: Optional[List[str]] = None,
    ):
        """
        Inicializa el servicio CDC.

        Args:
            nombre_cola: Nombre de la cola de RabbitMQ (opcional)
            colecciones: Lista de colecciones a monitorear (opcional)
            filtro_operaciones: Lista de operaciones a capturar (opcional)
        """
        self.nombre_cola = nombre_cola or configuracion.obtener_rabbitmq_cola_cambios()
        self.colecciones = colecciones
        self.filtro_operaciones = filtro_operaciones

        logger.info(f"Inicializando servicio CDC para cola '{self.nombre_cola}'")
        if self.colecciones:
            logger.info(f"Monitoreando colecciones: {', '.join(self.colecciones)}")
        if self.filtro_operaciones:
            logger.info(f"Filtrando operaciones: {', '.join(self.filtro_operaciones)}")

        # Monitor CDC
        self.monitor: Optional[MonitorCambiosMongoDB] = None

        # Control de señales
        self.terminando = False
        signal.signal(signal.SIGINT, self._handler_terminar)
        signal.signal(signal.SIGTERM, self._handler_terminar)

    def iniciar(self):
        """Inicia el servicio CDC."""
        logger.info("Iniciando servicio CDC...")

        # Esperar a que MongoDB esté listo (especialmente importante para el replica set)
        self._esperar_mongodb_disponible()

        # Intentar iniciar el monitor CDC
        intentos = 0
        max_intentos = 5
        
        while not self.terminando and intentos < max_intentos:
            try:
                # Crear y configurar monitor CDC
                self.monitor = crear_monitor_cdc(
                    nombre_cola=self.nombre_cola,
                    colecciones=self.colecciones,
                    filtro_operaciones=self.filtro_operaciones,
                )

                # Iniciar monitor
                if self.monitor.iniciar():
                    logger.success(
                        f"Servicio CDC iniciado. Monitoreando cambios para cola '{self.nombre_cola}'"
                    )
                    
                    # Mantener el servicio en ejecución
                    try:
                        while not self.terminando:
                            # Verificar si el monitor sigue activo
                            if not self.monitor or not self.monitor.esta_ejecutando():
                                logger.warning("Monitor CDC inactivo, reiniciando...")
                                self.detener()
                                # Reiniciar el monitor
                                self.monitor = crear_monitor_cdc(
                                    nombre_cola=self.nombre_cola,
                                    colecciones=self.colecciones,
                                    filtro_operaciones=self.filtro_operaciones,
                                )
                                if not self.monitor.iniciar():
                                    logger.error("No se pudo reiniciar el monitor CDC")
                                    time.sleep(10)  # Esperar antes de reintentar
                                    continue
                                logger.info("Monitor CDC reiniciado correctamente")
                            time.sleep(5)
                    except KeyboardInterrupt:
                        logger.info("Interrupción de teclado detectada")
                        self.terminando = True
                    except Exception as e:
                        logger.error(f"Error en el bucle principal del servicio CDC: {e}")
                    finally:
                        self.detener()
                    
                    return True
                else:
                    logger.error("No se pudo iniciar el monitor CDC")
            except Exception as e:
                logger.error(f"Error al iniciar el servicio CDC (intento {intentos+1}/{max_intentos}): {e}")
            
            intentos += 1
            if intentos < max_intentos and not self.terminando:
                logger.info(f"Reintentando en 10 segundos...")
                time.sleep(10)
                
        if intentos >= max_intentos:
            logger.critical(f"No se pudo iniciar el servicio CDC después de {max_intentos} intentos")
        
        self.detener()
        return False

    def _esperar_mongodb_disponible(self):
        """Espera a que MongoDB esté disponible antes de iniciar el monitor."""
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure, OperationFailure
        
        max_intentos = 30
        tiempo_espera = 5
        
        host = configuracion.obtener_mongodb_host()
        puerto = configuracion.obtener_mongodb_puerto()
        usuario = configuracion.obtener_mongodb_usuario()
        contraseña = configuracion.obtener_mongodb_contraseña()
        
        logger.info(f"Esperando a que MongoDB ({host}:{puerto}) esté disponible...")
        
        for intento in range(1, max_intentos + 1):
            if self.terminando:
                logger.info("Terminando durante la espera de MongoDB")
                return False
                
            try:
                uri = f"mongodb://{usuario}:{contraseña}@{host}:{puerto}/?replicaSet=rs0&authSource=admin"
                cliente = MongoClient(uri, serverSelectionTimeoutMS=5000)
                # Verificar que el replica set esté configurado correctamente
                estado_rs = cliente.admin.command('replSetGetStatus')
                miembros_ok = [m for m in estado_rs.get('members', []) if m.get('state') == 1]
                if miembros_ok:
                    logger.success(f"MongoDB está disponible con replica set configurado correctamente")
                    cliente.close()
                    return True
                else:
                    logger.warning(f"MongoDB replica set no tiene miembros primarios activos. Esperando... ({intento}/{max_intentos})")
            except (ConnectionFailure, OperationFailure) as e:
                logger.warning(f"MongoDB no está listo: {e} - Intento {intento}/{max_intentos}")
            except Exception as e:
                logger.error(f"Error inesperado al verificar MongoDB: {e}")
                
            time.sleep(tiempo_espera)
            
        logger.error(f"MongoDB no disponible después de {max_intentos} intentos")
        return False

    def detener(self):
        """Detiene el servicio CDC."""
        logger.info("Deteniendo servicio CDC...")

        if self.monitor:
            try:
                self.monitor.detener()
            except Exception as e:
                logger.error(f"Error al detener el monitor CDC: {e}")
            self.monitor = None

        logger.info("Servicio CDC detenido")

    def _handler_terminar(self, signum, frame):
        """Manejador de señales para terminar el servicio."""
        logger.info(f"Recibida señal de terminación ({signum})")
        self.terminando = True


def main():
    """Función principal para iniciar el servicio CDC."""
    # Configurar logging
    logger.remove()
    logger.add(
        sys.stderr,
        level=configuracion.obtener_nivel_log(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # Configuración opcional desde variables de entorno
    nombre_cola = os.environ.get("CDC_COLA_NOMBRE")
    colecciones_str = os.environ.get("CDC_COLECCIONES")
    colecciones = colecciones_str.split(",") if colecciones_str else None

    operaciones_str = os.environ.get("CDC_OPERACIONES")
    operaciones = operaciones_str.split(",") if operaciones_str else None

    # Crear e iniciar servicio
    servicio = ServicioCDC(
        nombre_cola=nombre_cola,
        colecciones=colecciones,
        filtro_operaciones=operaciones,
    )

    servicio.iniciar()


if __name__ == "__main__":
    main()
