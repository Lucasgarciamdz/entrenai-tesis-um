"""
Procesador de archivos PDF.

Este módulo contiene la clase ProcesadorPDF que se encarga de extraer
texto y metadatos de archivos PDF.
"""

import os
from typing import Dict, Any, Optional
import pypdf


class ProcesadorPDF:
    """Procesador para extraer texto de archivos PDF."""

    def __init__(self):
        """Inicializa el procesador de PDF."""
        pass

    def extraer_texto(self, ruta_archivo: str) -> str:
        """
        Extrae el texto completo de un archivo PDF.

        Args:
            ruta_archivo: Ruta al archivo PDF

        Returns:
            Texto extraído del PDF

        Raises:
            FileNotFoundError: Si el archivo no existe
        """
        if not os.path.exists(ruta_archivo):
            raise FileNotFoundError(f"El archivo {ruta_archivo} no existe")

        texto_completo = ""

        try:
            with open(ruta_archivo, "rb") as archivo:
                lector = pypdf.PdfReader(archivo)

                # Extraer texto de cada página
                for pagina in lector.pages:
                    texto_pagina = pagina.extract_text()
                    if texto_pagina:
                        texto_completo += texto_pagina + "\n\n"

            return texto_completo
        except Exception as e:
            print(f"Error al procesar el PDF {ruta_archivo}: {e}")
            return ""

    def extraer_metadatos(self, ruta_archivo: str) -> Dict[str, Any]:
        """
        Extrae metadatos de un archivo PDF.

        Args:
            ruta_archivo: Ruta al archivo PDF

        Returns:
            Diccionario con los metadatos del PDF

        Raises:
            FileNotFoundError: Si el archivo no existe
        """
        if not os.path.exists(ruta_archivo):
            raise FileNotFoundError(f"El archivo {ruta_archivo} no existe")

        try:
            with open(ruta_archivo, "rb") as archivo:
                lector = pypdf.PdfReader(archivo)
                info = lector.metadata

                # Construir diccionario de metadatos
                metadatos = {
                    "titulo": info.title if info and info.title else "",
                    "autor": info.author if info and info.author else "",
                    "creador": info.creator if info and info.creator else "",
                    "productor": info.producer if info and info.producer else "",
                    "numero_paginas": len(lector.pages),
                }

                return metadatos
        except Exception as e:
            print(f"Error al extraer metadatos del PDF {ruta_archivo}: {e}")
            return {}

    def procesar_archivo(self, ruta_archivo: str) -> Dict[str, Any]:
        """
        Procesa un archivo PDF extrayendo texto y metadatos.

        Args:
            ruta_archivo: Ruta al archivo PDF

        Returns:
            Diccionario con texto extraído y metadatos
        """
        resultado = {
            "texto": self.extraer_texto(ruta_archivo),
            "metadatos": self.extraer_metadatos(ruta_archivo),
            "ruta_archivo": ruta_archivo,
            "formato": "pdf",
        }

        return resultado
