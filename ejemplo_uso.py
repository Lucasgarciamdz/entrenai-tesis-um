#!/usr/bin/env python
"""
Ejemplo de uso del sistema de extracción y procesamiento de recursos de Moodle.

Este script muestra ejemplos de uso de las diferentes clases
implementadas para extraer y procesar recursos de Moodle.
"""

import os
from app.clientes import ClienteMoodle, ExtractorRecursosMoodle, RecolectorMoodle
from app.procesadores_archivos import ProcesadorArchivos
from app.config import configuracion


def ejemplo_cliente_basico():
    """Ejemplo básico de uso del cliente de Moodle."""
    print("\n=== EJEMPLO CLIENTE BÁSICO ===")

    # Crear cliente de Moodle usando la configuración
    cliente = ClienteMoodle(
        url_base=configuracion.obtener_url_moodle(),
        token=configuracion.obtener_token_moodle(),
    )

    # Obtener lista de cursos
    cursos = cliente.obtener_cursos()
    print(f"Cursos disponibles: {len(cursos)}")

    # Mostrar información básica de los cursos
    for curso in cursos[:3]:  # Mostrar solo los primeros 3
        print(f"- Curso ID: {curso.get('id')}, Nombre: {curso.get('fullname')}")

    # Obtener contenido de un curso específico
    if cursos:
        id_curso = cursos[1].get("id")
        print(f"\nObteniendo contenido del curso {id_curso}:")
        contenido = cliente.obtener_contenido_curso(id_curso)

        # Mostrar secciones del curso
        for seccion in contenido:
            print(f"- Sección: {seccion.get('name')}")
            print(f"  Módulos: {len(seccion.get('modules', []))}")


def ejemplo_extractor_recursos():
    """Ejemplo de uso del extractor de recursos."""
    print("\n=== EJEMPLO EXTRACTOR DE RECURSOS ===")

    # Crear cliente y extractor usando la configuración
    cliente = ClienteMoodle(
        url_base=configuracion.obtener_url_moodle(),
        token=configuracion.obtener_token_moodle(),
    )

    # Crear directorio para descargas si no existe
    directorio_descargas = configuracion.obtener_directorio_descargas()
    os.makedirs(directorio_descargas, exist_ok=True)

    extractor = ExtractorRecursosMoodle(cliente, directorio_descargas)

    # Obtener lista de cursos
    cursos = cliente.obtener_cursos()

    if not cursos:
        print("No se encontraron cursos disponibles")
        return

    # Seleccionar el primer curso para el ejemplo
    id_curso = cursos[1].get("id")
    nombre_curso = cursos[1].get("fullname")
    print(f"Procesando curso: {nombre_curso} (ID: {id_curso})")

    # Extraer información de recursos
    recursos = extractor.extraer_recursos_curso(id_curso)
    print(f"Recursos encontrados: {len(recursos)}")

    # Mostrar algunos recursos encontrados
    for recurso in recursos[:3]:  # Mostrar solo los primeros 3
        print(f"- Recurso: {recurso['nombre']} (Tipo: {recurso['tipo']})")
        print(f"  Contenidos: {len(recurso['contenidos'])}")

    # Descargar recursos usando tipos de recursos de la configuración
    tipos_recursos = configuracion.obtener_tipos_recursos_default()
    print(f"\nDescargando recursos ({', '.join(tipos_recursos)})...")
    archivos_descargados = extractor.descargar_recursos_curso(id_curso, tipos_recursos)

    # Mostrar resumen de descargas
    total_archivos = sum(len(archivos) for archivos in archivos_descargados.values())
    print(f"Total de archivos descargados: {total_archivos}")

    for tipo, archivos in archivos_descargados.items():
        print(f"- Tipo {tipo}: {len(archivos)} archivos")


def ejemplo_procesador_archivos():
    """Ejemplo de uso del procesador de archivos."""
    print("\n=== EJEMPLO PROCESADOR DE ARCHIVOS ===")

    # Crear procesador
    procesador = ProcesadorArchivos()

    # Procesar un archivo PDF si existe
    directorio_descargas = configuracion.obtener_directorio_descargas()

    if not os.path.exists(directorio_descargas):
        print(f"El directorio {directorio_descargas} no existe")
        return

    # Buscar archivos PDF
    archivos_pdf = []
    for raiz, _, archivos in os.walk(directorio_descargas):
        for archivo in archivos:
            if archivo.lower().endswith(".pdf"):
                archivos_pdf.append(os.path.join(raiz, archivo))

    if not archivos_pdf:
        print("No se encontraron archivos PDF para procesar")
        return

    print(f"Se encontraron {len(archivos_pdf)} archivos PDF")

    # Procesar el primer archivo PDF encontrado
    ruta_pdf = archivos_pdf[0]
    print(f"Procesando archivo: {ruta_pdf}")

    resultado = procesador.procesar_archivo(ruta_pdf)

    if resultado:
        # Mostrar metadatos
        print("\nMetadatos:")
        for clave, valor in resultado["metadatos"].items():
            print(f"- {clave}: {valor}")

        # Mostrar las primeras 100 caracteres del texto extraído
        texto = resultado["texto"]
        print(f"\nTexto extraído (primeros 100 caracteres):")
        print(texto[:100] + "..." if len(texto) > 100 else texto)


def ejemplo_recolector_completo():
    """Ejemplo de uso del recolector completo."""
    print("\n=== EJEMPLO RECOLECTOR COMPLETO ===")

    # Crear recolector usando la configuración
    recolector = RecolectorMoodle(
        url_moodle=configuracion.obtener_url_moodle(),
        token=configuracion.obtener_token_moodle(),
        directorio_descargas=configuracion.obtener_directorio_descargas(),
    )

    # Obtener lista de cursos
    cursos = recolector.cliente.obtener_cursos()

    if not cursos:
        print("No se encontraron cursos disponibles")
        return

    # Seleccionar el primer curso para el ejemplo
    id_curso = cursos[1].get("id")
    nombre_curso = cursos[1].get("fullname")
    print(f"Procesando curso: {nombre_curso} (ID: {id_curso})")

    # Recolectar y procesar recursos del curso usando configuración
    resultado = recolector.recolectar_curso(
        id_curso=id_curso,
        tipos_recursos=configuracion.obtener_tipos_recursos_default(),
        procesar=True,
    )

    # Mostrar estadísticas
    archivos_descargados = resultado["archivos_descargados"]
    total_archivos = sum(len(archivos) for archivos in archivos_descargados.values())

    print(f"\nEstadísticas de recolección:")
    print(f"- Curso: {resultado['nombre_curso']}")
    print(f"- Total de archivos descargados: {total_archivos}")

    for tipo, archivos in archivos_descargados.items():
        print(f"  * Tipo {tipo}: {len(archivos)} archivos")

    # Mostrar estadísticas de procesamiento
    resultados_procesamiento = resultado["resultados_procesamiento"]
    total_procesados = sum(len(docs) for docs in resultados_procesamiento.values())

    print(f"- Total de archivos procesados: {total_procesados}")

    for formato, docs in resultados_procesamiento.items():
        print(f"  * Formato {formato}: {len(docs)} archivos")


if __name__ == "__main__":
    # Mostrar información de configuración cargada
    print("=== INFORMACIÓN DE CONFIGURACIÓN ===")
    print(f"URL de Moodle: {configuracion.obtener_url_moodle()}")
    print(
        f"Token de Moodle: {'*' * 10 if configuracion.obtener_token_moodle() else 'No configurado'}"
    )
    print(f"Directorio de descargas: {configuracion.obtener_directorio_descargas()}")
    print(
        f"Tipos de recursos por defecto: {configuracion.obtener_tipos_recursos_default()}"
    )
    print(f"Nivel de log: {configuracion.obtener_nivel_log()}")
    print()

    # Ejecutar ejemplos
    try:
        ejemplo_cliente_basico()
        ejemplo_extractor_recursos()
        ejemplo_procesador_archivos()
        ejemplo_recolector_completo()
    except Exception as e:
        print(f"Error durante la ejecución de los ejemplos: {e}")
