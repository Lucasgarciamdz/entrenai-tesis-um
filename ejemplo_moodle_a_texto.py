#!/usr/bin/env python
"""
Ejemplo avanzado: Conversión de recursos Moodle a texto.

Este script descarga recursos de Moodle y los convierte a formato texto (.txt o .md)
para su posterior inserción en una base de datos MongoDB.
"""

import os
import shutil
from typing import Dict, List, Any, Optional

from app.clientes import RecolectorMoodle
from app.procesadores_archivos import ProcesadorArchivos, ProcesadorPDF
from app.config import configuracion


def convertir_a_texto(
    ruta_archivo: str, directorio_destino: str, usar_ocr: bool = True
) -> Optional[str]:
    """
    Convierte un archivo a formato texto.

    Args:
        ruta_archivo: Ruta al archivo original
        directorio_destino: Directorio donde guardar el archivo convertido
        usar_ocr: Si se debe usar OCR para extraer texto de PDFs

    Returns:
        Ruta al archivo de texto generado o None si no se pudo procesar
    """
    # Obtener extensión original del archivo
    _, extension = os.path.splitext(ruta_archivo)
    extension = extension.lower()

    # Si ya es un archivo de texto, simplemente copiarlo
    if extension in [".txt", ".md", ".markdown"]:
        # Crear nombre de archivo en destino
        nombre_base = os.path.basename(ruta_archivo)
        ruta_destino = os.path.join(directorio_destino, nombre_base)

        # Copiar el archivo
        shutil.copy2(ruta_archivo, ruta_destino)
        print(f"Archivo copiado: {ruta_destino}")
        return ruta_destino

    # Procesar el archivo según su tipo
    procesador = None

    if extension == ".pdf":
        # Usar el procesador de PDF con OCR si se solicita
        procesador = ProcesadorPDF(usar_ocr=usar_ocr, idioma="es")
    else:
        # Usar el procesador general para otros tipos
        procesador_archivos = ProcesadorArchivos()
        procesador = procesador_archivos.obtener_procesador(ruta_archivo)

    # Si no hay procesador disponible, devolver None
    if procesador is None:
        print(f"No hay procesador disponible para {ruta_archivo}")
        return None

    # Procesar el archivo
    resultado = procesador.procesar_archivo(ruta_archivo)

    if resultado and "texto" in resultado:
        # Obtener el nombre base del archivo original
        nombre_base = os.path.basename(ruta_archivo)
        nombre_sin_extension = os.path.splitext(nombre_base)[0]

        # Crear ruta de destino con extensión .txt
        ruta_destino = os.path.join(directorio_destino, f"{nombre_sin_extension}.txt")

        # Escribir el texto extraído a un archivo
        with open(ruta_destino, "w", encoding="utf-8") as f:
            # Incluir metadatos si están disponibles
            if "metadatos" in resultado:
                f.write("--- METADATOS ---\n")
                for clave, valor in resultado["metadatos"].items():
                    f.write(f"{clave}: {valor}\n")
                f.write("\n--- CONTENIDO ---\n\n")

            # Escribir el contenido principal
            f.write(resultado["texto"])

        print(f"Archivo convertido a texto: {ruta_destino}")
        return ruta_destino

    print(f"No se pudo extraer texto de {ruta_archivo}")
    return None


def convertir_recursos_curso(
    id_curso: int, directorio_destino: str, tipos_recursos: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Descarga recursos de un curso y los convierte a formato texto.

    Args:
        id_curso: ID del curso en Moodle
        directorio_destino: Directorio donde guardar los archivos de texto
        tipos_recursos: Lista de tipos de recursos a extraer

    Returns:
        Diccionario con información de los archivos procesados
    """
    # Crear recolector usando la configuración
    recolector = RecolectorMoodle(
        url_moodle=configuracion.obtener_url_moodle(),
        token=configuracion.obtener_token_moodle(),
        directorio_descargas=configuracion.obtener_directorio_descargas(),
    )

    # Obtener información del curso
    cursos = recolector.cliente.obtener_cursos()
    info_curso = next((c for c in cursos if c.get("id") == id_curso), {})
    nombre_curso = info_curso.get("fullname", f"Curso {id_curso}")

    print(f"Procesando curso: {nombre_curso} (ID: {id_curso})")

    # Descargar recursos del curso
    archivos_descargados = recolector.extractor.descargar_recursos_curso(
        id_curso, tipos_recursos
    )

    # Crear directorio para archivos de texto del curso
    directorio_curso = os.path.join(directorio_destino, f"curso_{id_curso}")
    os.makedirs(directorio_curso, exist_ok=True)

    # Procesar y convertir cada archivo descargado
    archivos_convertidos = []
    archivos_no_procesables = []

    # Aplanar la lista de archivos para procesamiento
    todos_archivos = []
    for tipo, archivos in archivos_descargados.items():
        todos_archivos.extend(archivos)

    # Procesar cada archivo
    total_archivos = len(todos_archivos)
    for i, ruta_archivo in enumerate(todos_archivos, 1):
        print(
            f"Convirtiendo archivo {i}/{total_archivos}: {os.path.basename(ruta_archivo)}"
        )
        ruta_texto = convertir_a_texto(ruta_archivo, directorio_curso, usar_ocr=True)

        if ruta_texto:
            archivos_convertidos.append(ruta_texto)
        else:
            archivos_no_procesables.append(ruta_archivo)

    # Crear resumen de resultados
    resultados = {
        "id_curso": id_curso,
        "nombre_curso": nombre_curso,
        "archivos_descargados": archivos_descargados,
        "total_descargados": len(todos_archivos),
        "archivos_convertidos": archivos_convertidos,
        "total_convertidos": len(archivos_convertidos),
        "archivos_no_procesables": archivos_no_procesables,
        "total_no_procesables": len(archivos_no_procesables),
        "directorio_textos": directorio_curso,
    }

    return resultados


def procesar_lista_archivos(
    lista_archivos: List[str], directorio_destino: str, usar_ocr: bool = True
) -> Dict[str, Any]:
    """
    Procesa una lista de archivos existentes y los convierte a formato texto.

    Args:
        lista_archivos: Lista de rutas a los archivos a procesar
        directorio_destino: Directorio donde guardar los archivos de texto
        usar_ocr: Si se debe usar OCR para extraer texto de PDFs

    Returns:
        Diccionario con información de los archivos procesados
    """
    os.makedirs(directorio_destino, exist_ok=True)

    archivos_convertidos = []
    archivos_no_procesables = []

    total_archivos = len(lista_archivos)
    for i, ruta_archivo in enumerate(lista_archivos, 1):
        print(
            f"Procesando archivo {i}/{total_archivos}: {os.path.basename(ruta_archivo)}"
        )

        # Verificar si el archivo existe
        if not os.path.exists(ruta_archivo):
            print(f"El archivo {ruta_archivo} no existe")
            archivos_no_procesables.append(ruta_archivo)
            continue

        # Convertir a texto
        ruta_texto = convertir_a_texto(ruta_archivo, directorio_destino, usar_ocr)

        if ruta_texto:
            archivos_convertidos.append(ruta_texto)
        else:
            archivos_no_procesables.append(ruta_archivo)

    # Crear resumen de resultados
    resultados = {
        "total_procesados": total_archivos,
        "archivos_convertidos": archivos_convertidos,
        "total_convertidos": len(archivos_convertidos),
        "archivos_no_procesables": archivos_no_procesables,
        "total_no_procesables": len(archivos_no_procesables),
        "directorio_textos": directorio_destino,
    }

    return resultados


def main():
    """Función principal del script."""
    print("=== CONVERSIÓN DE RECURSOS MOODLE A TEXTO ===")

    # Obtener lista de cursos
    recolector = RecolectorMoodle(
        url_moodle=configuracion.obtener_url_moodle(),
        token=configuracion.obtener_token_moodle(),
        directorio_descargas=configuracion.obtener_directorio_descargas(),
    )

    cursos = recolector.cliente.obtener_cursos()

    if not cursos:
        print("No se encontraron cursos disponibles")
        return

    # Mostrar cursos disponibles
    print("\nCursos disponibles:")
    for i, curso in enumerate(cursos, 1):
        print(f"{i}. {curso.get('fullname')} (ID: {curso.get('id')})")

    # Seleccionar el segundo curso para el ejemplo (puede cambiarse)
    curso_index = 1  # 0-based index
    if curso_index >= len(cursos):
        curso_index = 0

    id_curso = cursos[curso_index].get("id")
    nombre_curso = cursos[curso_index].get("fullname")

    # Directorio para archivos de texto
    directorio_textos = os.path.join(
        configuracion.obtener_directorio_descargas(), "archivos_texto"
    )

    # Procesar y convertir recursos del curso
    tipos_recursos = configuracion.obtener_tipos_recursos_default()
    print(f"\nConvirtiendo recursos del curso '{nombre_curso}' a texto...")
    print(f"Tipos de recursos: {', '.join(tipos_recursos)}")

    resultados = convertir_recursos_curso(
        id_curso=id_curso,
        directorio_destino=directorio_textos,
        tipos_recursos=tipos_recursos,
    )

    # Mostrar resumen de resultados
    print("\n=== RESUMEN DE CONVERSIÓN ===")
    print(f"Curso: {resultados['nombre_curso']}")
    print(f"Total de archivos descargados: {resultados['total_descargados']}")
    print(f"Archivos convertidos a texto: {resultados['total_convertidos']}")
    print(f"Archivos no procesables: {resultados['total_no_procesables']}")
    print(f"Directorio de archivos de texto: {resultados['directorio_textos']}")

    # Mostrar archivos no procesables si hay alguno
    if resultados["total_no_procesables"] > 0:
        print("\nArchivos que no pudieron ser procesados:")
        for archivo in resultados["archivos_no_procesables"]:
            print(f"- {os.path.basename(archivo)}")


def ejemplo_procesar_archivos_existentes():
    """
    Ejemplo de procesamiento de archivos ya descargados sin tener que descargarlos nuevamente.
    Útil para procesar archivos de un backup o de una descarga anterior.
    """
    print("\n=== CONVERSIÓN DE ARCHIVOS EXISTENTES A TEXTO ===")

    # Directorio donde están los archivos ya descargados
    directorio_origen = configuracion.obtener_directorio_descargas()

    # Directorio para los archivos de texto procesados
    directorio_destino = os.path.join(
        configuracion.obtener_directorio_descargas(), "archivos_texto_existentes"
    )

    # Buscar archivos PDF en el directorio de origen
    archivos_pdf = []
    for raiz, _, archivos in os.walk(directorio_origen):
        for archivo in archivos:
            if archivo.lower().endswith(".pdf"):
                archivos_pdf.append(os.path.join(raiz, archivo))

    print(f"Se encontraron {len(archivos_pdf)} archivos PDF para procesar")

    if not archivos_pdf:
        print("No hay archivos PDF para procesar")
        return

    # Procesar los archivos encontrados
    resultados = procesar_lista_archivos(
        lista_archivos=archivos_pdf,
        directorio_destino=directorio_destino,
        usar_ocr=True,
    )

    # Mostrar resumen
    print("\n=== RESUMEN DE CONVERSIÓN DE ARCHIVOS EXISTENTES ===")
    print(f"Total de archivos procesados: {resultados['total_procesados']}")
    print(f"Archivos convertidos a texto: {resultados['total_convertidos']}")
    print(f"Archivos no procesables: {resultados['total_no_procesables']}")
    print(f"Directorio de archivos de texto: {resultados['directorio_textos']}")


if __name__ == "__main__":
    # Ejecutar el ejemplo principal
    main()

    # Ejecutar ejemplo de procesamiento de archivos existentes
    ejemplo_procesar_archivos_existentes()
