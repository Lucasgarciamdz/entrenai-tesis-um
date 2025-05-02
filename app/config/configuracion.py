"""
Configuración de la aplicación.

Este módulo se encarga de cargar y proporcionar la configuración
desde las variables de entorno definidas en el archivo .env.
"""

import os
from typing import List, Any
from dotenv import load_dotenv


class Configuracion:
    """Gestor de configuración para la aplicación."""

    def __init__(self):
        """Inicializa la configuración cargando variables de entorno."""
        # Cargar variables de entorno desde .env
        load_dotenv()

    def obtener(self, clave: str, por_defecto: Any = None) -> Any:
        """
        Obtiene un valor de configuración por su clave.

        Args:
            clave: Nombre de la variable de entorno.
            por_defecto: Valor por defecto si la variable no existe.

        Returns:
            Valor de configuración o valor por defecto.
        """
        return os.environ.get(clave, por_defecto)

    def obtener_url_moodle(self) -> str:
        """
        Obtiene la URL base de Moodle.

        Returns:
            URL base de Moodle.
        """
        return self.obtener("MOODLE_URL_BASE", "http://localhost:8081")

    def obtener_token_moodle(self) -> str:
        """
        Obtiene el token de Moodle.

        Returns:
            Token de Moodle.
        """
        return self.obtener("MOODLE_TOKEN", "")

    def obtener_directorio_descargas(self) -> str:
        """
        Obtiene el directorio para descargas.

        Returns:
            Ruta al directorio de descargas.
        """
        return self.obtener("DIRECTORIO_DESCARGAS", "./archivos_moodle")

    def obtener_tipos_recursos_default(self) -> List[str]:
        """
        Obtiene la lista de tipos de recursos por defecto.

        Returns:
            Lista de tipos de recursos.
        """
        tipos_str = self.obtener("TIPOS_RECURSOS_DEFAULT", "resource,file,folder")
        return tipos_str.split(",")

    def obtener_mongodb_host(self) -> str:
        """
        Obtiene el host de MongoDB.

        Returns:
            Host de MongoDB.
        """
        return self.obtener("MONGODB_HOST", "localhost")

    def obtener_mongodb_puerto(self) -> int:
        """
        Obtiene el puerto de MongoDB.

        Returns:
            Puerto de MongoDB.
        """
        return int(self.obtener("MONGODB_PORT", "27017"))

    def obtener_mongodb_usuario(self) -> str:
        """
        Obtiene el usuario de MongoDB.

        Returns:
            Usuario de MongoDB.
        """
        return self.obtener("MONGODB_USERNAME", "")

    def obtener_mongodb_contraseña(self) -> str:
        """
        Obtiene la contraseña de MongoDB.

        Returns:
            Contraseña de MongoDB.
        """
        return self.obtener("MONGODB_PASSWORD", "")

    def obtener_mongodb_base_datos(self) -> str:
        """
        Obtiene el nombre de la base de datos de MongoDB.

        Returns:
            Nombre de la base de datos de MongoDB.
        """
        return self.obtener("MONGODB_DATABASE", "moodle_db")

    def obtener_rabbitmq_host(self) -> str:
        """
        Obtiene el host de RabbitMQ.

        Returns:
            Host de RabbitMQ.
        """
        return self.obtener("RABBITMQ_HOST", "localhost")

    def obtener_rabbitmq_puerto(self) -> int:
        """
        Obtiene el puerto de RabbitMQ.

        Returns:
            Puerto de RabbitMQ.
        """
        return int(self.obtener("RABBITMQ_PORT", "5672"))

    def obtener_rabbitmq_usuario(self) -> str:
        """
        Obtiene el usuario de RabbitMQ.

        Returns:
            Usuario de RabbitMQ.
        """
        return self.obtener("RABBITMQ_USERNAME", "guest")

    def obtener_rabbitmq_contraseña(self) -> str:
        """
        Obtiene la contraseña de RabbitMQ.

        Returns:
            Contraseña de RabbitMQ.
        """
        return self.obtener("RABBITMQ_PASSWORD", "guest")

    def obtener_rabbitmq_cola_cambios(self) -> str:
        """
        Obtiene el nombre de la cola de cambios de RabbitMQ.

        Returns:
            Nombre de la cola de cambios.
        """
        return self.obtener("RABBITMQ_COLA_CAMBIOS", "cambios_mongodb")

    def obtener_nivel_log(self) -> str:
        """
        Obtiene el nivel de logging.

        Returns:
            Nivel de logging.
        """
        return self.obtener("NIVEL_LOG", "INFO")


# Crear una instancia global para usar en toda la aplicación
configuracion = Configuracion()
