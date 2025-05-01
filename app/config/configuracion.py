"""
Configuración de la aplicación.

Este módulo se encarga de cargar y proporcionar la configuración
desde las variables de entorno definidas en el archivo .env.
"""

import os
from typing import List, Any, Optional
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

    def obtener_nivel_log(self) -> str:
        """
        Obtiene el nivel de logging.

        Returns:
            Nivel de logging.
        """
        return self.obtener("NIVEL_LOG", "INFO")


# Crear una instancia global para usar en toda la aplicación
configuracion = Configuracion()
