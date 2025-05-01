"""
Fábrica de procesadores de archivos.

Este módulo contiene la clase ProcesadorArchivos que actúa como una fábrica
para seleccionar el procesador adecuado según el tipo de archivo.
"""

from typing import Dict, List, Optional, Any
import os

from .procesador_pdf import ProcesadorPDF

# Importar otros procesadores cuando existan
# from .procesador_docx import ProcesadorDOCX
# from .procesador_html import ProcesadorHTML


class ProcesadorArchivos:
    """Fábrica para obtener el procesador correcto según el tipo de archivo."""

    def __init__(self):
        """Inicializa la fábrica de procesadores."""
        # Inicializar procesadores disponibles
        self.procesador_pdf = ProcesadorPDF()
        # self.procesador_docx = ProcesadorDOCX()
        # self.procesador_html = ProcesadorHTML()

    def obtener_procesador(self, ruta_archivo: str) -> Optional[Any]:
        """
        Obtiene el procesador adecuado según la extensión del archivo.

        Args:
            ruta_archivo: Ruta al archivo a procesar

        Returns:
            Instancia del procesador adecuado o None si no hay procesador disponible
        """
        _, extension = os.path.splitext(ruta_archivo)
        extension = extension.lower()

        if extension == ".pdf":
            return self.procesador_pdf
        # elif extension == '.docx':
        #     return self.procesador_docx
        # elif extension in ['.html', '.htm']:
        #     return self.procesador_html
        else:
            return None

    def procesar_archivo(self, ruta_archivo: str) -> Optional[Dict[str, Any]]:
        """
        Procesa un archivo utilizando el procesador adecuado.

        Args:
            ruta_archivo: Ruta al archivo a procesar

        Returns:
            Resultado del procesamiento o None si no hay procesador disponible
        """
        procesador = self.obtener_procesador(ruta_archivo)

        if procesador:
            try:
                return procesador.procesar_archivo(ruta_archivo)
            except Exception as e:
                print(f"Error al procesar el archivo {ruta_archivo}: {e}")
                return None
        else:
            print(f"No hay procesador disponible para el archivo {ruta_archivo}")
            return None

    def procesar_archivos(
        self, rutas_archivos: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Procesa múltiples archivos agrupando por tipo.

        Args:
            rutas_archivos: Lista de rutas a los archivos a procesar

        Returns:
            Diccionario con resultados agrupados por formato
        """
        resultados: Dict[str, List[Dict[str, Any]]] = {}

        total_archivos = len(rutas_archivos)
        for indice, ruta in enumerate(rutas_archivos, 1):
            print(
                f"Procesando archivo {indice}/{total_archivos}: {os.path.basename(ruta)}"
            )
            resultado = self.procesar_archivo(ruta)

            if resultado:
                formato = resultado.get("formato", "desconocido")

                if formato not in resultados:
                    resultados[formato] = []

                resultados[formato].append(resultado)

        return resultados
