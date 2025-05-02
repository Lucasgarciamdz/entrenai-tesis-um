"""
Conector para interactuar con MongoDB.

Este módulo define la clase ConectorMongoDB que proporciona
funcionalidad para interactuar con la base de datos MongoDB.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson import ObjectId

from app.database.modelos_documentos import (
    DocumentoBase,
    Curso,
    ContenidoTexto,
    DocumentoPDF,
)

logger = logging.getLogger(__name__)


class ConectorMongoDB:
    """
    Conector para interactuar con MongoDB utilizando los modelos de documentos.

    Esta clase proporciona métodos para guardar, actualizar, eliminar y buscar
    documentos en MongoDB utilizando los modelos de documentos definidos.
    """

    def __init__(
        self,
        host: str = "localhost",
        puerto: int = 27017,
        usuario: Optional[str] = None,
        contraseña: Optional[str] = None,
        base_datos: str = "moodle_db",
    ):
        """
        Inicializa el conector de MongoDB.

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
        self.conectar()

    def conectar(self) -> bool:
        """
        Establece conexión con la base de datos MongoDB.

        Returns:
            True si la conexión es exitosa, False en caso contrario
        """
        try:
            # Construir URI de conexión - Usamos 'admin' como base de datos de autenticación
            if self.usuario and self.contraseña:
                uri = f"mongodb://{self.usuario}:{self.contraseña}@{self.host}:{self.puerto}/{self.base_datos}"
            else:
                uri = f"mongodb://{self.host}:{self.puerto}/{self.base_datos}"

            # Intentar conectar
            self.cliente = MongoClient(uri)

            # Verificar conexión
            self.cliente.admin.command("ping")

            # Obtener referencia a la base de datos
            self.db = self.cliente[self.base_datos]

            print(f"Conexión exitosa a MongoDB en {self.host}:{self.puerto}")
            return True

        except PyMongoError as error:
            logger.error(f"Error al conectar a MongoDB: {error}")
            return False

    def desconectar(self):
        """Cierra la conexión con MongoDB."""
        if self.cliente is not None:
            self.cliente.close()
            print("Conexión a MongoDB cerrada")

    def guardar(self, documento: DocumentoBase) -> Optional[str]:
        """
        Guarda cualquier tipo de documento en la base de datos.

        Args:
            documento: Documento a guardar (debe ser una subclase de DocumentoBase).

        Returns:
            ID del documento insertado o None si ocurre un error.
        """
        try:
            # Determinar la colección según el tipo de documento
            coleccion = None
            if isinstance(documento, Curso):
                coleccion = self.db.cursos
            elif isinstance(documento, ContenidoTexto):
                coleccion = self.db.recursos
            elif isinstance(documento, DocumentoPDF):
                coleccion = self.db.archivos
            else:
                # Para otros tipos usar una colección genérica
                coleccion = self.db.documentos

            # Convertir a diccionario (excluyendo campos None)
            doc_dict = {k: v for k, v in documento.__dict__.items() if v is not None}

            # Asegurar que exista fecha_actualizacion (importante para el CDC por polling)
            doc_dict["fecha_actualizacion"] = datetime.now()

            # Insertar documento
            resultado = coleccion.insert_one(doc_dict)
            id_documento = str(resultado.inserted_id)

            # Si el documento tiene un atributo id, actualizarlo con el ID generado
            if hasattr(documento, "id"):
                documento.id = id_documento

            return id_documento

        except PyMongoError as error:
            logger.error(f"Error al guardar documento: {error}")
            return None

    def actualizar(self, documento: DocumentoBase) -> bool:
        """
        Actualiza un documento existente.

        Args:
            documento: Documento a actualizar (debe incluir un ID).

        Returns:
            True si la actualización fue exitosa, False en caso contrario.
        """
        if not hasattr(documento, "id") or not documento.id:
            logger.error("No se puede actualizar un documento sin ID")
            return False

        try:
            # Determinar la colección según el tipo de documento
            coleccion = None
            if isinstance(documento, Curso):
                coleccion = self.db.cursos
            elif isinstance(documento, ContenidoTexto):
                coleccion = self.db.recursos
            elif isinstance(documento, DocumentoPDF):
                coleccion = self.db.archivos
            else:
                # Para otros tipos usar una colección genérica
                coleccion = self.db.documentos

            # Convertir a diccionario (excluyendo campos None y el ID)
            doc_dict = {
                k: v
                for k, v in documento.__dict__.items()
                if v is not None and k != "id"
            }

            # Asegurar que exista fecha_actualizacion (importante para el CDC)
            doc_dict["fecha_actualizacion"] = datetime.now()

            # Actualizar documento
            resultado = coleccion.update_one(
                {"_id": ObjectId(documento.id)}, {"$set": doc_dict}
            )

            return resultado.modified_count > 0

        except PyMongoError as error:
            logger.error(f"Error al actualizar documento: {error}")
            return False

    def buscar_por_id(
        self, clase_documento, id_documento: str
    ) -> Optional[DocumentoBase]:
        """
        Busca un documento por su ID y lo convierte al tipo especificado.

        Args:
            clase_documento: Clase del documento a buscar.
            id_documento: ID del documento.

        Returns:
            Documento encontrado o None si no existe.
        """
        try:
            # Determinar la colección según el tipo de documento
            coleccion = None
            if clase_documento == Curso:
                coleccion = self.db.cursos
            elif clase_documento == ContenidoTexto:
                coleccion = self.db.recursos
            elif clase_documento == DocumentoPDF:
                coleccion = self.db.archivos
            else:
                # Para otros tipos usar una colección genérica
                coleccion = self.db.documentos

            # Buscar documento
            doc_dict = coleccion.find_one({"_id": ObjectId(id_documento)})

            if not doc_dict:
                return None

            # Convertir ObjectId a string
            if "_id" in doc_dict:
                doc_dict["id"] = str(doc_dict["_id"])
                del doc_dict["_id"]

            # Crear instancia de la clase
            documento = clase_documento(
                **{
                    k: v
                    for k, v in doc_dict.items()
                    if k in clase_documento.__annotations__
                }
            )

            # Asignar ID
            documento.id = doc_dict["id"]

            return documento

        except PyMongoError as error:
            logger.error(f"Error al buscar documento: {error}")
            return None

    def guardar_curso(self, curso: Curso) -> Optional[str]:
        """
        Guarda un curso en la base de datos.

        Args:
            curso: Documento del curso a guardar.

        Returns:
            ID del documento insertado o None si ocurre un error.
        """
        try:
            # Convertir a diccionario (excluyendo campos None)
            doc_curso = {k: v for k, v in curso.__dict__.items() if v is not None}

            # Agregar timestamp de creación si no existe
            if "fecha_actualizacion" not in doc_curso:
                doc_curso["fecha_actualizacion"] = datetime.now()

            # Insertar en la colección 'cursos'
            resultado = self.db.cursos.insert_one(doc_curso)
            return str(resultado.inserted_id)
        except PyMongoError as error:
            print(f"Error al guardar documento: {error}")
            return None

    def guardar_recurso(self, recurso: ContenidoTexto) -> Optional[str]:
        """
        Guarda un recurso en la base de datos.

        Args:
            recurso: Documento del recurso a guardar.

        Returns:
            ID del documento insertado o None si ocurre un error.
        """
        try:
            # Convertir a diccionario (excluyendo campos None)
            doc_recurso = {k: v for k, v in recurso.__dict__.items() if v is not None}

            # Agregar timestamp de creación si no existe
            if "fecha_actualizacion" not in doc_recurso:
                doc_recurso["fecha_actualizacion"] = datetime.now()

            # Insertar en la colección 'recursos'
            resultado = self.db.recursos.insert_one(doc_recurso)
            return str(resultado.inserted_id)
        except PyMongoError as error:
            print(f"Error al guardar documento: {error}")
            return None

    def guardar_archivo(self, archivo: DocumentoPDF) -> Optional[str]:
        """
        Guarda un archivo en la base de datos.

        Args:
            archivo: Documento del archivo a guardar.

        Returns:
            ID del documento insertado o None si ocurre un error.
        """
        try:
            # Convertir a diccionario (excluyendo campos None)
            doc_archivo = {k: v for k, v in archivo.__dict__.items() if v is not None}

            # Agregar timestamp de creación si no existe
            if "fecha_actualizacion" not in doc_archivo:
                doc_archivo["fecha_actualizacion"] = datetime.now()

            # Insertar en la colección 'archivos'
            resultado = self.db.archivos.insert_one(doc_archivo)
            return str(resultado.inserted_id)
        except PyMongoError as error:
            print(f"Error al guardar documento: {error}")
            return None

    def guardar_categoria(self, categoria: DocumentoBase) -> Optional[str]:
        """
        Guarda una categoría en la base de datos.

        Args:
            categoria: Documento de la categoría a guardar.

        Returns:
            ID del documento insertado o None si ocurre un error.
        """
        try:
            # Convertir a diccionario (excluyendo campos None)
            doc_categoria = {
                k: v for k, v in categoria.__dict__.items() if v is not None
            }

            # Agregar timestamp de creación si no existe
            if "fecha_actualizacion" not in doc_categoria:
                doc_categoria["fecha_actualizacion"] = datetime.now()

            # Insertar en la colección 'categorias'
            resultado = self.db.categorias.insert_one(doc_categoria)
            return str(resultado.inserted_id)
        except PyMongoError as error:
            print(f"Error al guardar documento: {error}")
            return None

    def obtener_curso_por_id(self, curso_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene un curso por su ID.

        Args:
            curso_id: ID del curso a buscar.

        Returns:
            Documento del curso o None si no se encuentra.
        """
        try:
            return self.db.cursos.find_one({"_id": ObjectId(curso_id)})
        except PyMongoError as error:
            logger.error(f"Error al buscar curso: {error}")
            return None

    def obtener_recurso_por_id(self, recurso_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene un recurso por su ID.

        Args:
            recurso_id: ID del recurso a buscar.

        Returns:
            Documento del recurso o None si no se encuentra.
        """
        try:
            return self.db.recursos.find_one({"_id": ObjectId(recurso_id)})
        except PyMongoError as error:
            logger.error(f"Error al buscar recurso: {error}")
            return None

    def obtener_archivo_por_id(self, archivo_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene un archivo por su ID.

        Args:
            archivo_id: ID del archivo a buscar.

        Returns:
            Documento del archivo o None si no se encuentra.
        """
        try:
            return self.db.archivos.find_one({"_id": ObjectId(archivo_id)})
        except PyMongoError as error:
            logger.error(f"Error al buscar archivo: {error}")
            return None

    def obtener_categoria_por_id(self, categoria_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene una categoría por su ID.

        Args:
            categoria_id: ID de la categoría a buscar.

        Returns:
            Documento de la categoría o None si no se encuentra.
        """
        try:
            return self.db.categorias.find_one({"_id": ObjectId(categoria_id)})
        except PyMongoError as error:
            logger.error(f"Error al buscar categoría: {error}")
            return None

    def obtener_recursos_por_curso(self, curso_id: int) -> List[Dict[str, Any]]:
        """
        Obtiene todos los recursos asociados a un curso específico.

        Args:
            curso_id: ID del curso.

        Returns:
            Lista de documentos de recursos.
        """
        try:
            return list(self.db.recursos.find({"id_curso": curso_id}))
        except PyMongoError as error:
            logger.error(f"Error al buscar recursos por curso: {error}")
            return []

    def obtener_archivos_por_recurso(self, recurso_id: str) -> List[Dict[str, Any]]:
        """
        Obtiene todos los archivos asociados a un recurso específico.

        Args:
            recurso_id: ID del recurso.

        Returns:
            Lista de documentos de archivos.
        """
        try:
            return list(self.db.archivos.find({"id_recurso": recurso_id}))
        except PyMongoError as error:
            logger.error(f"Error al buscar archivos por recurso: {error}")
            return []

    def actualizar_recurso(self, recurso_id: str, datos: Dict[str, Any]) -> bool:
        """
        Actualiza un recurso existente.

        Args:
            recurso_id: ID del recurso a actualizar.
            datos: Datos a actualizar.

        Returns:
            True si se actualizó correctamente, False en caso contrario.
        """
        try:
            # Agregar timestamp de actualización
            datos["fecha_actualizacion"] = datetime.now()

            # Actualizar documento
            resultado = self.db.recursos.update_one(
                {"_id": ObjectId(recurso_id)}, {"$set": datos}
            )
            return resultado.modified_count > 0
        except PyMongoError as error:
            logger.error(f"Error al actualizar recurso: {error}")
            return False

    def actualizar_archivo(self, archivo_id: str, datos: Dict[str, Any]) -> bool:
        """
        Actualiza un archivo existente.

        Args:
            archivo_id: ID del archivo a actualizar.
            datos: Datos a actualizar.

        Returns:
            True si se actualizó correctamente, False en caso contrario.
        """
        try:
            # Agregar timestamp de actualización
            datos["fecha_actualizacion"] = datetime.now()

            # Actualizar documento
            resultado = self.db.archivos.update_one(
                {"_id": ObjectId(archivo_id)}, {"$set": datos}
            )
            return resultado.modified_count > 0
        except PyMongoError as error:
            logger.error(f"Error al actualizar archivo: {error}")
            return False

    def eliminar_recurso(self, recurso_id: str) -> bool:
        """
        Elimina un recurso y todos sus archivos asociados.

        Args:
            recurso_id: ID del recurso a eliminar.

        Returns:
            True si se eliminó correctamente, False en caso contrario.
        """
        try:
            # Eliminar archivos asociados al recurso
            self.db.archivos.delete_many({"id_recurso": recurso_id})

            # Eliminar recurso
            resultado = self.db.recursos.delete_one({"_id": ObjectId(recurso_id)})
            return resultado.deleted_count > 0
        except PyMongoError as error:
            logger.error(f"Error al eliminar recurso: {error}")
            return False

    def eliminar_archivo(self, archivo_id: str) -> bool:
        """
        Elimina un archivo.

        Args:
            archivo_id: ID del archivo a eliminar.

        Returns:
            True si se eliminó correctamente, False en caso contrario.
        """
        try:
            resultado = self.db.archivos.delete_one({"_id": ObjectId(archivo_id)})
            return resultado.deleted_count > 0
        except PyMongoError as error:
            logger.error(f"Error al eliminar archivo: {error}")
            return False

    def esta_conectado(self) -> bool:
        """
        Verifica si la conexión a MongoDB está activa.

        Returns:
            True si la conexión está activa, False en caso contrario
        """
        try:
            if self.cliente is None:
                return False

            # Ping para verificar la conexión
            self.cliente.admin.command("ping")
            return True
        except Exception:
            return False
