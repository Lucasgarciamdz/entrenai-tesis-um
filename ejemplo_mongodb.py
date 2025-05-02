#!/usr/bin/env python
"""
Ejemplo avanzado: Guardar recursos procesados de Moodle en MongoDB.

Este script descarga recursos de Moodle, los convierte a formato texto
y guarda los resultados en una base de datos MongoDB.
"""

import os
import json
import datetime
from typing import Dict, List, Any, Optional

import pymongo
from pymongo.errors import ConnectionError, ServerSelectionTimeoutError

from app.clientes import RecolectorMoodle
from app.procesadores_archivos import ProcesadorArchivos, ProcesadorPDF
from app.config import configuracion


class ClienteMongoDB:
    """Cliente para interactuar con MongoDB."""

    def __init__(
        self,
        host: str = "localhost",
        puerto: int = 27017,
        usuario: Optional[str] = None,
        contraseña: Optional[str] = None,
        base_datos: str = "moodle_db",
    ):
        """
        Inicializa el cliente de MongoDB.

        Args:
            host: Host de MongoDB
            puerto: Puerto de MongoDB
            usuario: Usuario para autenticarse con MongoDB (opcional)
            contraseña: Contraseña para autenticarse con MongoDB (opcional)
            base_datos: Nombre de la base de datos
        """
        self.host = host
        self.puerto = puerto
        self.usuario = usuario
        self.contraseña = contraseña
        self.base_datos = base_datos
        self.cliente = None
        self.db = None

    def conectar(self) -> bool:
        """
        Establece conexión con la base de datos MongoDB.

        Returns:
            True si la conexión es exitosa, False en caso contrario
        """
        try:
            # Construir URI de conexión
            if self.usuario and self.contraseña:
                uri = f"mongodb://{self.usuario}:{self.contraseña}@{self.host}:{self.puerto}/{self.base_datos}"
            else:
                uri = f"mongodb://{self.host}:{self.puerto}/{self.base_datos}"

            # Intentar conectar
            self.cliente = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)

            # Verificar conexión
            self.cliente.server_info()

            # Obtener referencia a la base de datos
            self.db = self.cliente[self.base_datos]

            print(f"Conexión exitosa a MongoDB en {self.host}:{self.puerto}")
            return True

        except (ConnectionError, ServerSelectionTimeoutError) as e:
            print(f"Error al conectar a MongoDB: {e}")
            return False

    def desconectar(self):
        """Cierra la conexión con MongoDB."""
        if self.cliente:
            self.cliente.close()
            print("Conexión a MongoDB cerrada")

    def guardar_documento(
        self, coleccion: str, documento: Dict[str, Any]
    ) -> Optional[str]:
        """
        Guarda un documento en una colección.

        Args:
            coleccion: Nombre de la colección
            documento: Documento a guardar

        Returns:
            ID del documento guardado o None si falla
        """
        if not self.cliente or not self.db:
            print("No hay conexión activa con MongoDB")
            return None

        try:
            # Asegurar que el documento tenga una marca de tiempo
            if "fecha_creacion" not in documento:
                documento["fecha_creacion"] = datetime.datetime.now()

            # Insertar documento
            resultado = self.db[coleccion].insert_one(documento)
            return str(resultado.inserted_id)

        except Exception as e:
            print(f"Error al guardar documento en '{coleccion}': {e}")
            return None

    def buscar_documentos(
        self, coleccion: str, filtro: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca documentos en una colección.

        Args:
            coleccion: Nombre de la colección
            filtro: Filtro de búsqueda (opcional)

        Returns:
            Lista de documentos que coinciden con el filtro
        """
        if not self.cliente or not self.db:
            print("No hay conexión activa con MongoDB")
            return []

        try:
            if filtro is None:
                filtro = {}

            # Realizar búsqueda
            documentos = list(self.db[coleccion].find(filtro))

            # Convertir ObjectId a string para poder serializar a JSON
            for doc in documentos:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])

            return documentos

        except Exception as e:
            print(f"Error al buscar documentos en '{coleccion}': {e}")
            return []


def procesar_guardar_curso_mongodb(
    id_curso: int,
    cliente_mongo: ClienteMongoDB,
    tipos_recursos: Optional[List[str]] = None,
    usar_ocr: bool = True,
) -> Dict[str, Any]:
    """
    Procesa un curso de Moodle y guarda los textos extraídos en MongoDB.

    Args:
        id_curso: ID del curso en Moodle
        cliente_mongo: Cliente de MongoDB inicializado
        tipos_recursos: Lista de tipos de recursos a extraer (opcional)
        usar_ocr: Si se debe usar OCR para extraer texto de PDFs

    Returns:
        Diccionario con estadísticas del procesamiento
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
    shortname = info_curso.get("shortname", f"curso_{id_curso}")

    print(f"Procesando curso: {nombre_curso} (ID: {id_curso})")

    # Descargar recursos del curso
    archivos_descargados = recolector.extractor.descargar_recursos_curso(
        id_curso, tipos_recursos
    )

    # Procesar y guardar cada archivo descargado
    archivos_procesados = []
    archivos_no_procesables = []
    documentos_guardados = []

    # Aplanar la lista de archivos para procesamiento
    todos_archivos = []
    for tipo, archivos in archivos_descargados.items():
        todos_archivos.extend(archivos)

    # Procesar cada archivo
    total_archivos = len(todos_archivos)
    for i, ruta_archivo in enumerate(todos_archivos, 1):
        print(
            f"Procesando archivo {i}/{total_archivos}: {os.path.basename(ruta_archivo)}"
        )

        # Obtener procesador adecuado
        procesador = None
        _, extension = os.path.splitext(ruta_archivo)
        extension = extension.lower()

        if extension == ".pdf":
            # Usar el procesador de PDF con OCR si se solicita
            procesador = ProcesadorPDF(usar_ocr=usar_ocr, idioma="es")
        else:
            # Usar el procesador general para otros tipos
            procesador_archivos = ProcesadorArchivos()
            procesador = procesador_archivos.obtener_procesador(ruta_archivo)

        # Si no hay procesador disponible, continuar con el siguiente archivo
        if procesador is None:
            print(f"No hay procesador disponible para {ruta_archivo}")
            archivos_no_procesables.append(ruta_archivo)
            continue

        # Procesar el archivo
        try:
            resultado = procesador.procesar_archivo(ruta_archivo)

            if resultado and "texto" in resultado:
                # Crear documento para MongoDB
                documento = {
                    "id_curso": id_curso,
                    "nombre_curso": nombre_curso,
                    "shortname": shortname,
                    "nombre_archivo": os.path.basename(ruta_archivo),
                    "ruta_archivo": ruta_archivo,
                    "tipo_archivo": extension.lstrip("."),
                    "texto": resultado["texto"],
                    "metadatos": resultado.get("metadatos", {}),
                    "fecha_procesamiento": datetime.datetime.now(),
                }

                # Guardar documento en MongoDB en la colección correspondiente al curso
                coleccion = f"curso_{id_curso}"
                id_documento = cliente_mongo.guardar_documento(coleccion, documento)

                if id_documento:
                    print(f"Documento guardado en MongoDB con ID: {id_documento}")
                    documentos_guardados.append(id_documento)
                    archivos_procesados.append(ruta_archivo)
                else:
                    print(f"Error al guardar en MongoDB: {ruta_archivo}")
                    archivos_no_procesables.append(ruta_archivo)
            else:
                print(f"No se pudo extraer texto de {ruta_archivo}")
                archivos_no_procesables.append(ruta_archivo)

        except Exception as e:
            print(f"Error al procesar {ruta_archivo}: {e}")
            archivos_no_procesables.append(ruta_archivo)

    # Crear resumen de resultados
    resultados = {
        "id_curso": id_curso,
        "nombre_curso": nombre_curso,
        "total_archivos": total_archivos,
        "archivos_procesados": len(archivos_procesados),
        "archivos_no_procesables": len(archivos_no_procesables),
        "documentos_guardados": len(documentos_guardados),
    }

    # Guardar estadísticas en MongoDB
    cliente_mongo.guardar_documento(
        "estadisticas_procesamiento",
        {
            "tipo": "procesamiento_curso",
            "datos": resultados,
            "fecha": datetime.datetime.now(),
        },
    )

    return resultados


def procesar_todos_cursos_mongodb(
    cliente_mongo: ClienteMongoDB,
    tipos_recursos: Optional[List[str]] = None,
    usar_ocr: bool = True,
) -> List[Dict[str, Any]]:
    """
    Procesa todos los cursos disponibles y guarda los textos en MongoDB.

    Args:
        cliente_mongo: Cliente de MongoDB inicializado
        tipos_recursos: Lista de tipos de recursos a extraer (opcional)
        usar_ocr: Si se debe usar OCR para extraer texto de PDFs

    Returns:
        Lista con los resultados de procesamiento de cada curso
    """
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
        return []

    # Procesar cada curso
    resultados = []
    for i, curso in enumerate(cursos, 1):
        id_curso = curso.get("id")

        if not id_curso:
            continue

        print(f"\n=== Procesando curso {i}/{len(cursos)} ===")
        print(f"Curso: {curso.get('fullname')} (ID: {id_curso})")

        try:
            # Procesar y guardar curso en MongoDB
            resultado = procesar_guardar_curso_mongodb(
                id_curso=id_curso,
                cliente_mongo=cliente_mongo,
                tipos_recursos=tipos_recursos,
                usar_ocr=usar_ocr,
            )

            resultados.append(resultado)
        except Exception as e:
            print(f"Error al procesar curso {id_curso}: {e}")
            # Continuar con el siguiente curso en caso de error

    return resultados


def main():
    """Función principal del script."""
    print("=== GUARDAR RECURSOS MOODLE EN MONGODB ===")

    # Parámetros de conexión a MongoDB desde variables de entorno o valores por defecto
    host_mongo = os.environ.get("MONGODB_HOST", "localhost")
    puerto_mongo = int(os.environ.get("MONGODB_PORT", "27017"))
    usuario_mongo = os.environ.get("MONGODB_USERNAME", "admin")
    password_mongo = os.environ.get("MONGODB_PASSWORD", "password")
    base_datos_mongo = os.environ.get("MONGODB_DATABASE", "moodle_db")

    # Inicializar cliente de MongoDB
    cliente_mongo = ClienteMongoDB(
        host=host_mongo,
        puerto=puerto_mongo,
        usuario=usuario_mongo,
        contraseña=password_mongo,
        base_datos=base_datos_mongo,
    )

    # Intentar conexión
    if not cliente_mongo.conectar():
        print("No se pudo conectar a MongoDB. Verifica que el servicio esté activo.")
        print("Para activar MongoDB, ejecuta: docker-compose up -d mongodb")
        return

    try:
        # Tipos de recursos a procesar
        tipos_recursos = configuracion.obtener_tipos_recursos_default()
        print(f"Tipos de recursos a procesar: {', '.join(tipos_recursos)}")

        # Preguntar al usuario qué acción realizar
        print("\nSeleccione una opción:")
        print("1. Procesar un curso específico")
        print("2. Procesar todos los cursos disponibles")

        opcion = input("Opción (1/2): ").strip()

        if opcion == "1":
            # Mostrar cursos disponibles
            recolector = RecolectorMoodle(
                url_moodle=configuracion.obtener_url_moodle(),
                token=configuracion.obtener_token_moodle(),
                directorio_descargas=configuracion.obtener_directorio_descargas(),
            )

            cursos = recolector.cliente.obtener_cursos()

            print("\nCursos disponibles:")
            for i, curso in enumerate(cursos, 1):
                print(f"{i}. {curso.get('fullname')} (ID: {curso.get('id')})")

            # Solicitar selección de curso al usuario
            seleccion = input("\nSeleccione el número del curso a procesar: ").strip()

            try:
                indice_seleccionado = int(seleccion) - 1
                if 0 <= indice_seleccionado < len(cursos):
                    curso_seleccionado = cursos[indice_seleccionado]
                    id_curso = curso_seleccionado.get("id")

                    # Procesar curso seleccionado
                    resultado = procesar_guardar_curso_mongodb(
                        id_curso=id_curso,
                        cliente_mongo=cliente_mongo,
                        tipos_recursos=tipos_recursos,
                        usar_ocr=True,
                    )

                    # Mostrar estadísticas
                    print("\n=== ESTADÍSTICAS DE PROCESAMIENTO ===")
                    print(f"Curso: {resultado['nombre_curso']}")
                    print(f"Total de archivos: {resultado['total_archivos']}")
                    print(f"Archivos procesados: {resultado['archivos_procesados']}")
                    print(
                        f"Archivos no procesables: {resultado['archivos_no_procesables']}"
                    )
                    print(
                        f"Documentos guardados en MongoDB: {resultado['documentos_guardados']}"
                    )
                else:
                    print("Selección inválida.")
            except (ValueError, IndexError):
                print("Selección inválida. Debe ingresar un número válido.")

        elif opcion == "2":
            # Procesar todos los cursos
            print("\nIniciando procesamiento de todos los cursos...")

            resultados = procesar_todos_cursos_mongodb(
                cliente_mongo=cliente_mongo,
                tipos_recursos=tipos_recursos,
                usar_ocr=True,
            )

            # Mostrar estadísticas generales
            total_cursos = len(resultados)
            total_archivos = sum(r["total_archivos"] for r in resultados)
            total_procesados = sum(r["archivos_procesados"] for r in resultados)
            total_no_procesables = sum(r["archivos_no_procesables"] for r in resultados)
            total_guardados = sum(r["documentos_guardados"] for r in resultados)

            print("\n=== ESTADÍSTICAS GLOBALES ===")
            print(f"Total de cursos procesados: {total_cursos}")
            print(f"Total de archivos: {total_archivos}")
            print(f"Total de archivos procesados: {total_procesados}")
            print(f"Total de archivos no procesables: {total_no_procesables}")
            print(f"Total de documentos guardados en MongoDB: {total_guardados}")

        else:
            print("Opción inválida.")

    finally:
        # Cerrar conexión con MongoDB
        cliente_mongo.desconectar()


if __name__ == "__main__":
    main()

    print("\n=== COMANDOS PARA GESTIONAR MONGODB ===")
    print("Para iniciar MongoDB: docker-compose up -d mongodb")
    print("Para detener MongoDB: docker-compose stop mongodb")
    print("Para ver los logs de MongoDB: docker-compose logs mongodb")
    print("\nPara conectarse a MongoDB usando mongosh:")
    print("docker exec -it mongodb mongosh -u admin -p password")
