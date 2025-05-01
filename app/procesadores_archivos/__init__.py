"""
Módulo de procesadores de archivos.

Este paquete contiene las clases necesarias para
procesar diferentes tipos de archivos y extraer su contenido.
"""

from .procesador_archivos import ProcesadorArchivos
from .procesador_pdf import ProcesadorPDF

__all__ = ["ProcesadorArchivos", "ProcesadorPDF"]
