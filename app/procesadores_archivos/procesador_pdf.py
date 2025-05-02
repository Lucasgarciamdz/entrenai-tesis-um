"""
Procesador de archivos PDF.

Este módulo contiene la clase ProcesadorPDF que se encarga de extraer
texto, imágenes, fórmulas y metadatos de archivos PDF utilizando tanto
extracción directa como técnicas de OCR.
"""

import os
import numpy as np
from typing import Dict, Any, List

import pypdf

# Importaciones para OCR
try:
    import pytesseract
    from pdf2image import convert_from_path

    SOPORTE_OCR = True
except ImportError:
    SOPORTE_OCR = False

# Importaciones para OCR avanzado (opcional)
try:
    import easyocr

    SOPORTE_OCR_AVANZADO = True
except ImportError:
    SOPORTE_OCR_AVANZADO = False


class ProcesadorPDF:
    """Procesador para extraer texto e imágenes de archivos PDF."""

    def __init__(self, usar_ocr: bool = False, idioma: str = "es"):
        """
        Inicializa el procesador de PDF.

        Args:
            usar_ocr: Si es True, utiliza OCR para extraer texto de imágenes
            idioma: Idioma para el OCR (por defecto español - 'es' para EasyOCR y 'spa' para Tesseract)
        """
        global SOPORTE_OCR_AVANZADO  # Declarar la variable como global

        self.usar_ocr = usar_ocr
        self.idioma = idioma
        self.idioma_tesseract = "spa"  # Tesseract usa 'spa' para español
        self.soporte_ocr_avanzado = (
            SOPORTE_OCR_AVANZADO  # Guardar estado en la instancia
        )

        if usar_ocr and not SOPORTE_OCR:
            print(
                "Advertencia: Las dependencias para OCR no están instaladas. "
                "Instala pdf2image y pytesseract con: pip install pdf2image pytesseract"
            )
            self.usar_ocr = False

        if SOPORTE_OCR_AVANZADO:
            # EasyOCR usa 'es' para español, no 'spa'
            idioma_easyocr = idioma if idioma != "spa" else "es"
            try:
                self.reader = easyocr.Reader([idioma_easyocr, "en"])
                print(f"EasyOCR inicializado con idioma: {idioma_easyocr}")
            except Exception as e:
                print(f"Error al inicializar EasyOCR: {e}")
                SOPORTE_OCR_AVANZADO = (
                    False  # Ahora sí podemos modificar la variable global
                )
                self.soporte_ocr_avanzado = False

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

            # Si hay poco texto y OCR está habilitado, asumimos que puede ser un PDF escaneado
            if self.usar_ocr and (
                len(texto_completo.strip()) < 100 or "/Encoding" in texto_completo
            ):
                texto_ocr = self._aplicar_ocr(ruta_archivo)
                if texto_ocr:
                    return texto_ocr

            return texto_completo
        except Exception as e:
            print(f"Error al procesar el PDF {ruta_archivo}: {e}")
            return ""

    def _aplicar_ocr(self, ruta_archivo: str) -> str:
        """
        Aplica OCR a un archivo PDF.

        Args:
            ruta_archivo: Ruta al archivo PDF

        Returns:
            Texto extraído con OCR
        """
        if not SOPORTE_OCR:
            return ""

        try:
            # Convertir PDF a imágenes
            imagenes = convert_from_path(ruta_archivo, 300)
            texto_completo = ""

            # OCR básico con pytesseract
            for img in imagenes:
                if self.soporte_ocr_avanzado:  # Usar la variable de instancia
                    # Usar EasyOCR para mejor precisión (especialmente para fórmulas)
                    resultados = self.reader.readtext(np.array(img))
                    for _, texto in resultados:
                        texto_completo += texto + " "
                    texto_completo += "\n\n"
                else:
                    # Usar pytesseract
                    texto = pytesseract.image_to_string(img, lang=self.idioma_tesseract)
                    texto_completo += texto + "\n\n"

            return texto_completo
        except Exception as e:
            print(f"Error al aplicar OCR al PDF {ruta_archivo}: {e}")
            return ""

    def extraer_imagenes(self, ruta_archivo: str) -> List[Dict[str, Any]]:
        """
        Extrae imágenes de un archivo PDF.

        Args:
            ruta_archivo: Ruta al archivo PDF

        Returns:
            Lista de diccionarios con información de las imágenes extraídas
        """
        if not os.path.exists(ruta_archivo):
            raise FileNotFoundError(f"El archivo {ruta_archivo} no existe")

        imagenes = []

        try:
            with open(ruta_archivo, "rb") as archivo:
                lector = pypdf.PdfReader(archivo)

                for i, pagina in enumerate(lector.pages):
                    for j, imagen in enumerate(pagina.images):
                        # Guardar información de la imagen
                        info_imagen = {
                            "pagina": i + 1,
                            "indice": j + 1,
                            "nombre": imagen.name,
                            "tipo": self._obtener_tipo_imagen(imagen.name),
                            "datos": imagen.data,
                            "ancho": imagen.width if hasattr(imagen, "width") else None,
                            "alto": (
                                imagen.height if hasattr(imagen, "height") else None
                            ),
                        }
                        imagenes.append(info_imagen)

            return imagenes
        except Exception as e:
            print(f"Error al extraer imágenes del PDF {ruta_archivo}: {e}")
            return []

    def _obtener_tipo_imagen(self, nombre: str) -> str:
        """
        Determina el tipo de imagen basado en su nombre.

        Args:
            nombre: Nombre de la imagen

        Returns:
            Tipo de imagen (extensión)
        """
        if nombre.lower().endswith(".jpg") or nombre.lower().endswith(".jpeg"):
            return "jpeg"
        elif nombre.lower().endswith(".png"):
            return "png"
        elif nombre.lower().endswith(".tiff") or nombre.lower().endswith(".tif"):
            return "tiff"
        else:
            return "desconocido"

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

                # Comprobar si hay campos de formulario de manera segura
                tiene_formulario = False
                if hasattr(lector, "get_fields"):
                    try:
                        fields = lector.get_fields()
                        tiene_formulario = fields is not None and len(fields) > 0
                    except Exception as e:
                        print(
                            f"Advertencia: No se pudieron obtener los campos del formulario: {e}"
                        )

                # Comprobar si hay texto extraíble de manera segura
                tiene_texto = False
                try:
                    tiene_texto = any(pagina.extract_text() for pagina in lector.pages)
                except Exception as e:
                    print(f"Advertencia: Error al verificar texto extraíble: {e}")

                # Construir diccionario de metadatos
                metadatos = {
                    "titulo": (
                        info.title
                        if info and hasattr(info, "title") and info.title
                        else ""
                    ),
                    "autor": (
                        info.author
                        if info and hasattr(info, "author") and info.author
                        else ""
                    ),
                    "creador": (
                        info.creator
                        if info and hasattr(info, "creator") and info.creator
                        else ""
                    ),
                    "productor": (
                        info.producer
                        if info and hasattr(info, "producer") and info.producer
                        else ""
                    ),
                    "numero_paginas": (
                        len(lector.pages)
                        if hasattr(lector, "pages") and lector.pages
                        else 0
                    ),
                    "tiene_formulario": tiene_formulario,
                    "tiene_texto_extraible": tiene_texto,
                }

                return metadatos
        except Exception as e:
            print(f"Error al extraer metadatos del PDF {ruta_archivo}: {e}")
            # Devolver un diccionario de metadatos vacío en caso de error
            return {
                "titulo": "",
                "autor": "",
                "creador": "",
                "productor": "",
                "numero_paginas": 0,
                "tiene_formulario": False,
                "tiene_texto_extraible": False,
                "error": str(e),
            }

    def guardar_imagenes(self, ruta_archivo: str, directorio_destino: str) -> List[str]:
        """
        Extrae y guarda las imágenes de un PDF en un directorio.

        Args:
            ruta_archivo: Ruta al archivo PDF
            directorio_destino: Directorio donde guardar las imágenes

        Returns:
            Lista de rutas a las imágenes guardadas
        """
        # Crear directorio si no existe
        if not os.path.exists(directorio_destino):
            os.makedirs(directorio_destino)

        imagenes = self.extraer_imagenes(ruta_archivo)
        rutas_guardadas = []

        for img in imagenes:
            # Generar nombre de archivo
            nombre_base = os.path.basename(ruta_archivo).split(".")[0]
            extension = "jpg" if img["tipo"] == "jpeg" else img["tipo"]
            if extension == "desconocido":
                extension = "png"  # Por defecto

            nombre_archivo = (
                f"{nombre_base}_p{img['pagina']}_i{img['indice']}.{extension}"
            )
            ruta_destino = os.path.join(directorio_destino, nombre_archivo)

            # Guardar imagen
            try:
                with open(ruta_destino, "wb") as archivo:
                    archivo.write(img["datos"])
                rutas_guardadas.append(ruta_destino)
            except Exception as e:
                print(f"Error al guardar imagen {nombre_archivo}: {e}")

        return rutas_guardadas

    def procesar_archivo(
        self, ruta_archivo: str, extraer_imagenes: bool = False
    ) -> Dict[str, Any]:
        """
        Procesa un archivo PDF extrayendo texto, metadatos y opcionalmente imágenes.

        Args:
            ruta_archivo: Ruta al archivo PDF
            extraer_imagenes: Si es True, también extrae información de imágenes

        Returns:
            Diccionario con texto extraído, metadatos e información de imágenes
        """
        resultado = {
            "texto": self.extraer_texto(ruta_archivo),
            "metadatos": self.extraer_metadatos(ruta_archivo),
            "ruta_archivo": ruta_archivo,
            "formato": "pdf",
        }

        if extraer_imagenes:
            resultado["imagenes"] = self.extraer_imagenes(ruta_archivo)

        # Detectar si el PDF probablemente contiene fórmulas matemáticas
        texto = resultado["texto"]
        if (
            "\\frac" in texto
            or "\\sum" in texto
            or "\\int" in texto
            or "$" in texto
            or "\\begin{equation}" in texto
        ):
            resultado["contiene_formulas"] = True

        return resultado
