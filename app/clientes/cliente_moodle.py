"""
Cliente para interactuar con la API REST de Moodle.

Este módulo contiene la clase ClienteMoodle que permite realizar
peticiones a la API de Moodle y obtener información de cursos y recursos.
"""

import requests
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin


class ClienteMoodle:
    """Cliente para interactuar con la API REST de Moodle."""

    def __init__(self, url_base: str, token: str):
        """
        Inicializa el cliente de Moodle.

        Args:
            url_base: URL base de la instalación de Moodle
            token: Token de autenticación para la API web
        """
        self.url_base = url_base.rstrip("/")
        self.token = token
        self.endpoint = f"{self.url_base}/webservice/rest/server.php"

    def _hacer_peticion(
        self, funcion: str, parametros: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Realiza una petición a la API de Moodle.

        Args:
            funcion: Nombre de la función de la API (wsfunction)
            parametros: Parámetros adicionales para la llamada

        Returns:
            Respuesta de la API en formato diccionario

        Raises:
            requests.HTTPError: Si la petición falla
        """
        params = {
            "wstoken": self.token,
            "moodlewsrestformat": "json",
            "wsfunction": funcion,
        }

        if parametros:
            params.update(parametros)

        respuesta = requests.get(self.endpoint, params=params, timeout=30)
        respuesta.raise_for_status()

        return respuesta.json()

    def obtener_cursos(self) -> List[Dict[str, Any]]:
        """
        Obtiene la lista de todos los cursos disponibles.

        Returns:
            Lista de cursos con sus metadatos
        """
        return self._hacer_peticion("core_course_get_courses")

    def obtener_contenido_curso(self, id_curso: int) -> List[Dict[str, Any]]:
        """
        Obtiene el contenido completo de un curso específico.

        Args:
            id_curso: ID del curso en Moodle

        Returns:
            Lista de secciones con módulos y recursos del curso
        """
        return self._hacer_peticion("core_course_get_contents", {"courseid": id_curso})

    def obtener_url_descarga(self, url_archivo: str) -> str:
        """
        Convierte una URL relativa de un archivo en una URL de descarga completa.

        Args:
            url_archivo: URL relativa del archivo en Moodle

        Returns:
            URL completa para descargar el archivo
        """
        # Si ya es una URL completa, devolverla
        if url_archivo.startswith("http"):
            return url_archivo

        # Construir URL completa
        return urljoin(self.url_base, url_archivo)

    def descargar_archivo(self, url_archivo: str, ruta_destino: str) -> bool:
        """
        Descarga un archivo de Moodle.

        Args:
            url_archivo: URL del archivo a descargar
            ruta_destino: Ruta local donde guardar el archivo

        Returns:
            True si la descarga fue exitosa, False en caso contrario
        """
        url_completa = self.obtener_url_descarga(url_archivo)

        # Añadir token si es necesario
        if "?" in url_completa:
            url_completa += f"&token={self.token}"
        else:
            url_completa += f"?token={self.token}"

        try:
            respuesta = requests.get(url_completa, stream=True, timeout=30)
            respuesta.raise_for_status()

            with open(ruta_destino, "wb") as archivo:
                for chunk in respuesta.iter_content(chunk_size=8192):
                    archivo.write(chunk)

            return True
        except Exception as e:
            print(f"Error al descargar archivo: {e}")
            return False
