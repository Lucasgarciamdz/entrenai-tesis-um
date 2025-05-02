"""
Recolector de recursos de Moodle.

Este módulo contiene la clase RecolectorMoodle que integra la extracción
y el procesamiento de los recursos de Moodle.
"""

from typing import Dict, List, Any, Optional

from .cliente_moodle import ClienteMoodle
from .extractor_recursos_moodle import ExtractorRecursosMoodle
from ..procesadores_archivos.procesador_archivos import ProcesadorArchivos


class RecolectorMoodle:
    """
    Clase que integra la extracción de datos de Moodle y su procesamiento.
    Responsabilidad: coordinar el flujo completo de extracción y procesamiento.
    """

    def __init__(
        self, url_moodle: str, token: str, directorio_descargas: str = "./descargas"
    ):
        """
        Inicializa el recolector de Moodle.

        Args:
            url_moodle: URL base de la instalación de Moodle
            token: Token de autenticación para la API web
            directorio_descargas: Directorio donde se guardarán los archivos
        """
        self.cliente = ClienteMoodle(url_moodle, token)
        self.extractor = ExtractorRecursosMoodle(self.cliente, directorio_descargas)
        self.procesador = ProcesadorArchivos()
        self.directorio_descargas = directorio_descargas

    def recolectar_curso(
        self,
        id_curso: int,
        tipos_recursos: Optional[List[str]] = None,
        procesar: bool = True,
    ) -> Dict[str, Any]:
        """
        Recolecta y opcionalmente procesa todos los recursos de un curso.

        Args:
            id_curso: ID del curso en Moodle
            tipos_recursos: Lista de tipos de recursos a extraer
            procesar: Si se deben procesar los archivos después de descargarlos

        Returns:
            Diccionario con información del curso, archivos descargados y resultados procesados
        """
        # Obtener metadatos del curso
        cursos = self.cliente.obtener_cursos()
        info_curso = next((c for c in cursos if c.get("id") == id_curso), {})

        # Descargar recursos
        archivos_descargados = self.extractor.descargar_recursos_curso(
            id_curso, tipos_recursos
        )

        resultado = {
            "id_curso": id_curso,
            "nombre_curso": info_curso.get("fullname", f"Curso {id_curso}"),
            "archivos_descargados": archivos_descargados,
            "resultados_procesamiento": {},
        }

        # Procesar archivos si se solicita
        if procesar:
            resultados_procesamiento = {}

            # Aplanar la lista de archivos para procesamiento
            todos_archivos = []
            for archivos in archivos_descargados.values():
                todos_archivos.extend(archivos)

            if todos_archivos:
                resultados_procesamiento = self.procesador.procesar_archivos(
                    todos_archivos
                )

            resultado["resultados_procesamiento"] = resultados_procesamiento

        return resultado

    def recolectar_todos_cursos(
        self,
        tipos_recursos: Optional[List[str]] = None,
        procesar: bool = True,
        max_cursos: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recolecta y opcionalmente procesa recursos de todos los cursos disponibles.

        Args:
            tipos_recursos: Lista de tipos de recursos a extraer
            procesar: Si se deben procesar los archivos después de descargarlos
            max_cursos: Número máximo de cursos a procesar (None para todos)

        Returns:
            Lista de resultados por curso
        """
        cursos = self.cliente.obtener_cursos()
        resultados = []

        # Limitar número de cursos si se especifica
        if max_cursos is not None:
            cursos = cursos[:max_cursos]

        total_cursos = len(cursos)
        for indice, curso in enumerate(cursos, 1):
            id_curso = curso.get("id")
            if id_curso:
                print(
                    f"Procesando curso {indice}/{total_cursos}: {curso.get('fullname', f'ID {id_curso}')}"
                )
                try:
                    resultado = self.recolectar_curso(
                        id_curso, tipos_recursos, procesar
                    )
                    resultados.append(resultado)
                except Exception as e:
                    print(f"Error al procesar curso {id_curso}: {e}")

        return resultados

    def obtener_estadisticas_recoleccion(
        self, resultados: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Genera estadísticas a partir de los resultados de recolección.

        Args:
            resultados: Lista de resultados de recolección por curso

        Returns:
            Diccionario con estadísticas de la recolección
        """
        estadisticas = {
            "total_cursos": len(resultados),
            "total_archivos": 0,
            "archivos_por_tipo": {},
            "total_procesados": 0,
            "procesados_por_formato": {},
        }

        # Calcular estadísticas de archivos descargados
        for resultado in resultados:
            archivos_descargados = resultado.get("archivos_descargados", {})
            for tipo, archivos in archivos_descargados.items():
                total_tipo = len(archivos)
                estadisticas["total_archivos"] += total_tipo

                if tipo not in estadisticas["archivos_por_tipo"]:
                    estadisticas["archivos_por_tipo"][tipo] = 0
                estadisticas["archivos_por_tipo"][tipo] += total_tipo

            # Estadísticas de procesamiento
            resultados_procesamiento = resultado.get("resultados_procesamiento", {})
            for formato, docs in resultados_procesamiento.items():
                total_formato = len(docs)
                estadisticas["total_procesados"] += total_formato

                if formato not in estadisticas["procesados_por_formato"]:
                    estadisticas["procesados_por_formato"][formato] = 0
                estadisticas["procesados_por_formato"][formato] += total_formato

        return estadisticas
