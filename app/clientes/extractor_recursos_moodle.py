"""
Extractor de recursos de Moodle.

Este módulo contiene la clase ExtractorRecursosMoodle que se encarga de extraer
y descargar recursos de los cursos de Moodle utilizando el cliente de la API.
"""

import os
from typing import Dict, List, Any, Optional
from .cliente_moodle import ClienteMoodle


class ExtractorRecursosMoodle:
    """Extrae recursos específicos de Moodle usando el cliente."""

    def __init__(self, cliente: ClienteMoodle, directorio_destino: str = "./descargas"):
        """
        Inicializa el extractor de recursos.

        Args:
            cliente: Instancia de ClienteMoodle para comunicación con API
            directorio_destino: Directorio donde se guardarán los archivos
        """
        self.cliente = cliente
        self.directorio_destino = directorio_destino

        # Crear directorio si no existe
        os.makedirs(self.directorio_destino, exist_ok=True)

    def extraer_recursos_curso(self, id_curso: int) -> List[Dict[str, Any]]:
        """
        Extrae información de todos los recursos de un curso.

        Args:
            id_curso: ID del curso en Moodle

        Returns:
            Lista de recursos encontrados con metadatos
        """
        contenido = self.cliente.obtener_contenido_curso(id_curso)
        recursos = []

        # Iterar sobre secciones y módulos
        for seccion in contenido:
            seccion_nombre = seccion.get("name", "Sin nombre")

            # Extraer módulos dentro de la sección
            for modulo in seccion.get("modules", []):
                tipo_modulo = modulo.get("modname")
                nombre_modulo = modulo.get("name", "Sin nombre")

                # Recopilar información básica del recurso
                info_recurso = {
                    "id": modulo.get("id"),
                    "id_curso": id_curso,
                    "seccion": seccion_nombre,
                    "nombre": nombre_modulo,
                    "tipo": tipo_modulo,
                    "url": modulo.get("url", ""),
                    "contenidos": [],
                }

                # Extraer contenidos específicos según el tipo
                if "contents" in modulo:
                    for contenido in modulo.get("contents", []):
                        info_recurso["contenidos"].append(
                            {
                                "tipo": contenido.get("type"),
                                "nombre_archivo": contenido.get("filename", ""),
                                "ruta_archivo": contenido.get("filepath", ""),
                                "tamaño": contenido.get("filesize", 0),
                                "url_descarga": contenido.get("fileurl", ""),
                                "mimetype": contenido.get("mimetype", ""),
                            }
                        )

                recursos.append(info_recurso)

        return recursos

    def descargar_recursos_curso(
        self, id_curso: int, tipos_recursos: Optional[List[str]] = None
    ) -> Dict[str, List[str]]:
        """
        Descarga recursos específicos de un curso.

        Args:
            id_curso: ID del curso en Moodle
            tipos_recursos: Lista de tipos de recursos a descargar (ej: ['resource', 'file'])
                           Si es None, se descargan todos los tipos

        Returns:
            Diccionario con rutas de archivos descargados agrupados por tipo de recurso
        """
        recursos = self.extraer_recursos_curso(id_curso)
        archivos_descargados: Dict[str, List[str]] = {}

        # Crear directorio para el curso
        directorio_curso = os.path.join(self.directorio_destino, f"curso_{id_curso}")
        os.makedirs(directorio_curso, exist_ok=True)

        for recurso in recursos:
            tipo = recurso["tipo"]

            # Filtrar por tipo de recurso si se especificó
            if tipos_recursos and tipo not in tipos_recursos:
                continue

            # Inicializar lista si no existe
            if tipo not in archivos_descargados:
                archivos_descargados[tipo] = []

            # Crear subdirectorio para el tipo de recurso
            directorio_tipo = os.path.join(directorio_curso, tipo)
            os.makedirs(directorio_tipo, exist_ok=True)

            # Descargar contenidos del recurso
            for contenido in recurso["contenidos"]:
                url_descarga = contenido.get("url_descarga")
                if not url_descarga:
                    continue

                # Crear ruta de destino para el archivo
                nombre_archivo = contenido.get("nombre_archivo")
                if not nombre_archivo:
                    # Extraer nombre del archivo de la URL si no está disponible
                    nombre_archivo = os.path.basename(url_descarga.split("?")[0])
                    if not nombre_archivo:
                        nombre_archivo = f"recurso_{recurso['id']}"

                # Manejar posible colisión de nombres de archivo
                ruta_destino = os.path.join(directorio_tipo, nombre_archivo)
                contador = 1
                nombre_base, extension = os.path.splitext(nombre_archivo)
                while os.path.exists(ruta_destino):
                    nuevo_nombre = f"{nombre_base}_{contador}{extension}"
                    ruta_destino = os.path.join(directorio_tipo, nuevo_nombre)
                    contador += 1

                # Descargar el archivo
                exito = self.cliente.descargar_archivo(url_descarga, ruta_destino)

                if exito:
                    archivos_descargados[tipo].append(ruta_destino)
                    print(f"Archivo descargado: {ruta_destino}")

        return archivos_descargados

    def descargar_todos_recursos(
        self,
        tipos_recursos: Optional[List[str]] = None,
        ids_cursos: Optional[List[int]] = None,
    ) -> Dict[int, Dict[str, List[str]]]:
        """
        Descarga recursos de múltiples cursos.

        Args:
            tipos_recursos: Lista de tipos de recursos a descargar
            ids_cursos: Lista de IDs de cursos a procesar. Si es None, se procesan todos.

        Returns:
            Diccionario con IDs de cursos como claves y resultados de descargas como valores
        """
        if ids_cursos is None:
            # Obtener todos los cursos disponibles
            cursos = self.cliente.obtener_cursos()
            ids_cursos = [curso.get("id") for curso in cursos if curso.get("id")]

        resultado_total: Dict[int, Dict[str, List[str]]] = {}

        for id_curso in ids_cursos:
            print(f"Procesando curso ID: {id_curso}")
            resultado = self.descargar_recursos_curso(id_curso, tipos_recursos)
            resultado_total[id_curso] = resultado

            # Mostrar estadísticas
            total_archivos = sum(len(archivos) for archivos in resultado.values())
            print(f"Curso {id_curso}: {total_archivos} archivos descargados")

        return resultado_total
