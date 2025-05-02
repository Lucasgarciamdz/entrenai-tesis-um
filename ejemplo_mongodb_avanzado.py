#!/usr/bin/env python
"""
Ejemplo avanzado: Guardar recursos de Moodle en MongoDB usando modelos de documentos.

Este script muestra cómo utilizar modelos de documentos Pydantic para guardar
y recuperar datos de cursos y recursos de Moodle en MongoDB.
"""

import os
import sys
import concurrent.futures
import multiprocessing
from typing import Optional, Tuple
import time

from app.clientes import RecolectorMoodle
from app.procesadores_archivos import ProcesadorArchivos, ProcesadorPDF
from app.config import configuracion
from app.database.modelos_documentos import (
    Curso,
    ContenidoTexto,
    DocumentoPDF,
    DocumentoHTML,
)
from app.database.conector_mongodb import ConectorMongoDB


def procesar_cursos():
    """Procesa todos los cursos disponibles y guarda en MongoDB usando modelos de documentos."""
    # Parámetros de conexión a MongoDB desde variables de entorno o valores por defecto
    host_mongo = os.environ.get("MONGODB_HOST", "localhost")
    puerto_mongo = int(os.environ.get("MONGODB_PORT", "27017"))
    usuario_mongo = os.environ.get("MONGODB_USERNAME", "admin")
    password_mongo = os.environ.get("MONGODB_PASSWORD", "password")
    base_datos_mongo = os.environ.get("MONGODB_DATABASE", "moodle_db")

    # Crear conector a MongoDB
    conector = ConectorMongoDB(
        host=host_mongo,
        puerto=puerto_mongo,
        usuario=usuario_mongo,
        contraseña=password_mongo,
        base_datos=base_datos_mongo,
    )

    # Conectar a MongoDB
    if not conector.conectar():
        print("No se pudo conectar a MongoDB. Verifica que el servicio esté activo.")
        print("Para activar MongoDB, ejecuta: docker-compose up -d mongodb")
        sys.exit(1)

    # Crear recolector usando la configuración
    recolector = RecolectorMoodle(
        url_moodle=configuracion.obtener_url_moodle(),
        token=configuracion.obtener_token_moodle(),
        directorio_descargas=configuracion.obtener_directorio_descargas(),
    )

    # Obtener lista de cursos
    cursos_moodle = recolector.cliente.obtener_cursos()

    if not cursos_moodle:
        print("No se encontraron cursos disponibles")
        return

    # Guardar información de cada curso en MongoDB
    for curso_moodle in cursos_moodle:
        # Extraer datos del curso
        id_curso = curso_moodle.get("id")

        if id_curso != 2:
            continue

        nombre_curso = curso_moodle.get("fullname", "")
        codigo_curso = curso_moodle.get("shortname", "")
        descripcion_curso = curso_moodle.get("summary", "")

        # Crear modelo de documento para el curso
        curso_documento = Curso(
            id_moodle=id_curso,
            nombre=nombre_curso,
            codigo=codigo_curso,
            descripcion=descripcion_curso,
        )

        # Guardar curso en MongoDB
        id_documento = conector.guardar(curso_documento)

        if id_documento:
            print(f"Curso guardado en MongoDB: {nombre_curso} (ID: {id_documento})")

            # Procesar recursos del curso
            procesar_recursos_curso(
                id_curso=id_curso, conector=conector, recolector=recolector
            )
        else:
            print(f"Error al guardar curso en MongoDB: {nombre_curso}")

    # Desconectar de MongoDB
    conector.desconectar()


def procesar_recursos_curso(
    id_curso: int, conector: ConectorMongoDB, recolector: RecolectorMoodle
):
    """
    Procesa los recursos de un curso y los guarda en MongoDB usando modelos de documentos.

    Args:
        id_curso: ID del curso en Moodle
        conector: Conector a MongoDB inicializado
        recolector: Recolector de Moodle inicializado
    """
    print(f"\nProcesando recursos del curso ID: {id_curso}")

    # Obtener información del curso
    cursos = recolector.cliente.obtener_cursos()
    info_curso = next((c for c in cursos if c.get("id") == id_curso), {})
    nombre_curso = info_curso.get("fullname", f"Curso {id_curso}")

    # Descargar recursos del curso
    tipos_recursos = configuracion.obtener_tipos_recursos_default()
    archivos_descargados = recolector.extractor.descargar_recursos_curso(
        id_curso, tipos_recursos
    )

    # Aplanar la lista de archivos para procesamiento
    todos_archivos = []
    for tipo, archivos in archivos_descargados.items():
        todos_archivos.extend(archivos)

    # Separar archivos por tipo
    archivos_simples = []
    archivos_complejos = []

    for ruta_archivo in todos_archivos:
        _, extension = os.path.splitext(ruta_archivo)
        extension = extension.lower().lstrip(".")

        # Los archivos simples son procesados más rápido
        if extension in ["txt", "htm", "html", "md", "markdown"]:
            archivos_simples.append(ruta_archivo)
        else:
            archivos_complejos.append(ruta_archivo)

    total_archivos = len(todos_archivos)
    print(f"Total de archivos: {total_archivos}")
    print(f"Archivos simples (procesamiento rápido): {len(archivos_simples)}")
    print(f"Archivos complejos (procesamiento lento): {len(archivos_complejos)}")

    # Configuración de paralelismo
    num_nucleos = multiprocessing.cpu_count()
    print(f"Número de núcleos de CPU disponibles: {num_nucleos}")

    # Iniciar temporizador para medir rendimiento
    tiempo_inicio = time.time()
    resultados = []

    # 1. Procesar archivos simples con hilos (son I/O bound)
    if archivos_simples:
        print("\nProcesando archivos simples con hilos...")
        args_simples = [
            (i, ruta, id_curso, nombre_curso, conector)
            for i, ruta in enumerate(archivos_simples)
        ]

        # Limitar el número de hilos para no saturar recursos
        max_workers_simple = min(10, len(archivos_simples))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers_simple
        ) as executor:
            resultados_simples = list(
                executor.map(procesar_archivo_paralelo, args_simples)
            )
            resultados.extend(resultados_simples)

    # 2. Procesar archivos complejos con CPU bound (PDFs con OCR)
    if archivos_complejos:
        print("\nProcesando archivos complejos...")

        # Para archivos complejos usamos ThreadPoolExecutor pero con menos hilos
        # Esto evita problemas con bibliotecas de OCR y mantiene estable la conexión a MongoDB
        args_complejos = [
            (i + len(archivos_simples), ruta, id_curso, nombre_curso, conector)
            for i, ruta in enumerate(archivos_complejos)
        ]

        # Usamos menos hilos para archivos complejos para no saturar los recursos
        # Especialmente importante para PDFs con OCR que son intensivos en memoria
        max_workers_complex = min(3, num_nucleos, len(archivos_complejos))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers_complex
        ) as executor:
            resultados_complejos = list(
                executor.map(procesar_archivo_paralelo, args_complejos)
            )
            resultados.extend(resultados_complejos)

    # Calcular estadísticas de rendimiento
    tiempo_fin = time.time()
    tiempo_total = tiempo_fin - tiempo_inicio

    # Mostrar resumen
    procesados_ok = sum(1 for res in resultados if res)
    print(
        f"\nResumen: {procesados_ok} de {total_archivos} archivos procesados correctamente"
    )
    print(f"Tiempo total de procesamiento: {tiempo_total:.2f} segundos")

    # Calcular velocidad promedio
    if total_archivos > 0:
        print(
            f"Velocidad promedio: {tiempo_total / total_archivos:.2f} segundos por archivo"
        )
        print(f"Rendimiento: {total_archivos / tiempo_total:.2f} archivos por segundo")


def procesar_archivo_paralelo(args: Tuple) -> bool:
    """
    Función wrapper para procesar un archivo en paralelo con hilos.

    Args:
        args: Tupla con (indice, ruta_archivo, id_curso, nombre_curso, conector)

    Returns:
        True si el archivo se procesó correctamente, False en caso contrario
    """
    indice, ruta_archivo, id_curso, nombre_curso, conector = args
    nombre_archivo = os.path.basename(ruta_archivo)
    print(f"[Hilo] Procesando archivo {indice + 1}: {nombre_archivo}")

    try:
        documento = procesar_archivo(ruta_archivo, id_curso, nombre_curso, conector)
        if documento:
            print(f"[Hilo] Archivo procesado y guardado con éxito: {nombre_archivo}")
            return True
        else:
            print(f"[Hilo] No se pudo procesar el archivo: {nombre_archivo}")
            return False
    except Exception as e:
        print(f"[Hilo] Error al procesar archivo {nombre_archivo}: {str(e)}")
        return False


def procesar_archivo(
    ruta_archivo: str, id_curso: int, nombre_curso: str, conector: ConectorMongoDB
) -> Optional[ContenidoTexto]:
    """
    Procesa un archivo y lo guarda en MongoDB usando el modelo de documento adecuado.

    Args:
        ruta_archivo: Ruta al archivo a procesar
        id_curso: ID del curso al que pertenece el archivo
        nombre_curso: Nombre del curso
        conector: Conector a MongoDB

    Returns:
        Modelo de documento creado o None si falla
    """
    # Obtener extensión del archivo
    _, extension = os.path.splitext(ruta_archivo)
    extension = extension.lower().lstrip(".")

    # Optimización para archivos de texto simples
    if extension in ["txt", "md", "markdown", "html", "htm"]:
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                texto = f.read()

            # Crear documento genérico para archivos de texto
            documento = ContenidoTexto(
                id_curso=id_curso,
                nombre_curso=nombre_curso,
                ruta_archivo=ruta_archivo,
                nombre_archivo=os.path.basename(ruta_archivo),
                tipo_archivo=extension,
                texto=texto,
                metadatos={},
            )

            # Guardar en MongoDB
            id_documento = conector.guardar(documento)
            if id_documento:
                documento.id = id_documento
                return documento
            return None
        except Exception as e:
            print(f"Error procesando archivo de texto simple {ruta_archivo}: {e}")
            return None

    # Para HTML simple
    if extension in ["html", "htm"]:
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                texto_html = f.read()

            # Crear procesador para extraer texto limpio
            procesador_archivos = ProcesadorArchivos()
            procesador = procesador_archivos.obtener_procesador(ruta_archivo)

            if procesador is None:
                # Si no hay procesador, al menos guardar el contenido bruto
                documento = DocumentoHTML(
                    id_curso=id_curso,
                    nombre_curso=nombre_curso,
                    ruta_archivo=ruta_archivo,
                    nombre_archivo=os.path.basename(ruta_archivo),
                    texto=texto_html,
                    metadatos={},
                )
            else:
                # Procesar con el procesador adecuado
                resultado = procesador.procesar_archivo(ruta_archivo)

                if not resultado or "texto" not in resultado:
                    return None

                documento = DocumentoHTML(
                    id_curso=id_curso,
                    nombre_curso=nombre_curso,
                    ruta_archivo=ruta_archivo,
                    nombre_archivo=os.path.basename(ruta_archivo),
                    texto=resultado["texto"],
                    metadatos=resultado.get("metadatos", {}),
                )

            # Guardar en MongoDB
            id_documento = conector.guardar(documento)
            if id_documento:
                documento.id = id_documento
                return documento
            return None
        except Exception as e:
            print(f"Error procesando HTML {ruta_archivo}: {e}")
            return None

    # Para otros tipos de archivo (incluidos PDFs)
    # Determinar tipo de procesador
    procesador = None

    if extension == "pdf":
        # Usar procesador PDF con OCR
        procesador = ProcesadorPDF(usar_ocr=True, idioma="es")
    else:
        # Usar procesador general
        procesador_archivos = ProcesadorArchivos()
        procesador = procesador_archivos.obtener_procesador(ruta_archivo)

    # Si no hay procesador disponible, salir
    if procesador is None:
        print(f"No hay procesador disponible para {ruta_archivo}")
        return None

    try:
        # Procesar archivo
        resultado = procesador.procesar_archivo(ruta_archivo)

        if not resultado or "texto" not in resultado:
            print(f"No se pudo extraer texto de {ruta_archivo}")
            return None

        # Crear modelo de documento adecuado según el tipo de archivo
        documento = None

        if extension == "pdf":
            # Crear documento PDF
            documento = DocumentoPDF(
                id_curso=id_curso,
                nombre_curso=nombre_curso,
                ruta_archivo=ruta_archivo,
                nombre_archivo=os.path.basename(ruta_archivo),
                texto=resultado["texto"],
                metadatos=resultado.get("metadatos", {}),
                total_paginas=resultado.get("metadatos", {}).get("numero_paginas", 0),
                procesado_con_ocr=True,
                contiene_formulas=resultado.get("contiene_formulas", False),
                tiene_imagenes=bool(resultado.get("imagenes", [])),
            )
        else:
            # Crear documento genérico
            documento = ContenidoTexto(
                id_curso=id_curso,
                nombre_curso=nombre_curso,
                ruta_archivo=ruta_archivo,
                nombre_archivo=os.path.basename(ruta_archivo),
                tipo_archivo=extension,
                texto=resultado["texto"],
                metadatos=resultado.get("metadatos", {}),
            )

        # Guardar documento en MongoDB
        id_documento = conector.guardar(documento)

        if id_documento:
            # Actualizar el ID del documento
            documento.id = id_documento
            return documento
        else:
            print(f"Error al guardar en MongoDB: {ruta_archivo}")
            return None

    except Exception as e:
        print(f"Error al procesar {ruta_archivo}: {e}")
        return None


def buscar_textos_curso(id_curso: int):
    """
    Busca todos los contenidos de texto de un curso en MongoDB.

    Args:
        id_curso: ID del curso
    """
    # Conectar a MongoDB
    conector = ConectorMongoDB()

    if not conector.conectar():
        print("No se pudo conectar a MongoDB.")
        return

    # Buscar todos los contenidos del curso
    try:
        contenidos = conector.buscar(ContenidoTexto, {"id_curso": id_curso})

        print(
            f"\nSe encontraron {len(contenidos)} documentos para el curso ID {id_curso}"
        )

        # Mostrar información de cada documento
        for i, contenido in enumerate(contenidos, 1):
            print(f"\nDocumento {i}:")
            print(f"  ID: {contenido.id}")
            print(f"  Archivo: {contenido.nombre_archivo}")
            print(f"  Tipo: {contenido.tipo_archivo}")
            print(f"  Tamaño texto: {len(contenido.texto)} caracteres")

            # Mostrar primeros 100 caracteres del texto
            texto_preview = contenido.texto[:100].replace("\n", " ")
            if len(contenido.texto) > 100:
                texto_preview += "..."
            print(f"  Preview: {texto_preview}")

    finally:
        conector.desconectar()


def realizar_benchmark():
    """Realiza un benchmark para comparar el rendimiento del procesamiento paralelo"""
    print("\n=== BENCHMARK DE RENDIMIENTO ===")

    # Preparar un conjunto de prueba
    # Este código debería adaptarse según las necesidades reales

    print("1. Modo secuencial (un archivo a la vez)")
    print("2. Modo paralelo (usando hilos)")

    opcion = input("Seleccione modo de benchmark (1/2): ").strip()

    # Aquí se implementaría la lógica del benchmark
    print(f"Benchmark no implementado. Seleccionó la opción {opcion}")
    print("Para implementar un benchmark completo, se requeriría:")
    print("- Un conjunto de datos de prueba consistente")
    print("- Mediciones precisas de tiempo para cada enfoque")


def main():
    """Función principal del script."""
    print("=== GUARDAR RECURSOS MOODLE EN MONGODB (AVANZADO) ===")

    # Mostrar opciones
    print("\nSeleccione una opción:")
    print("1. Procesar todos los cursos y guardar en MongoDB")
    print("2. Buscar contenido de un curso específico")
    print("3. Ejecutar benchmark de rendimiento")

    opcion = input("Opción (1/2/3): ").strip()

    if opcion == "1":
        procesar_cursos()

    elif opcion == "2":
        # Obtener lista de cursos para mostrar al usuario
        recolector = RecolectorMoodle(
            url_moodle=configuracion.obtener_url_moodle(),
            token=configuracion.obtener_token_moodle(),
            directorio_descargas=configuracion.obtener_directorio_descargas(),
        )

        cursos = recolector.cliente.obtener_cursos()

        if not cursos:
            print("No se encontraron cursos disponibles")
            return

        print("\nCursos disponibles:")
        for i, curso in enumerate(cursos, 1):
            print(f"{i}. {curso.get('fullname')} (ID: {curso.get('id')})")

        # Solicitar selección de curso
        seleccion = input("\nSeleccione el número del curso: ").strip()

        try:
            indice = int(seleccion) - 1
            if 0 <= indice < len(cursos):
                id_curso = cursos[indice].get("id")
                buscar_textos_curso(id_curso)
            else:
                print("Selección inválida")
        except ValueError:
            print("Por favor, ingrese un número válido")

    elif opcion == "3":
        realizar_benchmark()

    else:
        print("Opción inválida")

    print("\n=== COMANDOS PARA GESTIONAR MONGODB ===")
    print("Para iniciar MongoDB: docker-compose up -d mongodb")
    print("Para detener MongoDB: docker-compose stop mongodb")
    print("Para ver los logs de MongoDB: docker-compose logs mongodb")
    print("\nPara conectarse a MongoDB usando mongosh:")
    print("docker exec -it mongodb mongosh -u admin -p password")


if __name__ == "__main__":
    main()
