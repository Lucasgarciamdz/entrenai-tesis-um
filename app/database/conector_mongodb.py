"""
Conector para interactuar con MongoDB.

Este módulo define la clase ConectorMongoDB que proporciona
funcionalidad para interactuar con la base de datos MongoDB.
"""

import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime

import pymongo
from pydantic import BaseModel

from app.database.modelos_documentos import DocumentoBase


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

    def conectar(self) -> bool:
        """
        Establece conexión con la base de datos MongoDB.

        Returns:
            True si la conexión es exitosa, False en caso contrario
        """
        try:
            # Construir URI de conexión - Usamos 'admin' como base de datos de autenticación
            if self.usuario and self.contraseña:
                uri = f"mongodb://{self.usuario}:{self.contraseña}@{self.host}:{self.puerto}/admin"
            else:
                uri = f"mongodb://{self.host}:{self.puerto}"

            # Intentar conectar
            self.cliente = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)

            # Verificar conexión
            self.cliente.server_info()

            # Obtener referencia a la base de datos
            self.db = self.cliente[self.base_datos]

            print(f"Conexión exitosa a MongoDB en {self.host}:{self.puerto}")
            return True

        except Exception as e:
            print(f"Error al conectar a MongoDB: {e}")
            return False

    def desconectar(self):
        """Cierra la conexión con MongoDB."""
        if self.cliente is not None:
            self.cliente.close()
            print("Conexión a MongoDB cerrada")

    def guardar(self, documento: DocumentoBase) -> Optional[str]:
        """
        Guarda un documento en MongoDB.

        Args:
            documento: Instancia de DocumentoBase a guardar

        Returns:
            ID del documento guardado o None si falla
        """
        if self.db is None:
            print("No hay conexión activa con MongoDB")
            return None

        try:
            # Obtener colección
            coleccion = getattr(documento.Config, "collection", None)
            if not coleccion:
                coleccion = documento.__class__.__name__.lower()

            # Convertir documento a diccionario
            doc_dict = documento.to_dict()

            # Insertar documento
            resultado = self.db[coleccion].insert_one(doc_dict)
            return str(resultado.inserted_id)

        except Exception as e:
            print(f"Error al guardar documento: {e}")
            return None

    def actualizar(self, documento: DocumentoBase) -> bool:
        """
        Actualiza un documento existente en MongoDB.

        Args:
            documento: Instancia de DocumentoBase a actualizar

        Returns:
            True si la actualización fue exitosa, False en caso contrario
        """
        if self.db is None:
            print("No hay conexión activa con MongoDB")
            return False

        try:
            # Actualizar fecha
            documento.fecha_actualizacion = datetime.now()

            # Obtener colección
            coleccion = getattr(documento.Config, "collection", None)
            if not coleccion:
                coleccion = documento.__class__.__name__.lower()

            # Convertir documento a diccionario
            doc_dict = documento.to_dict()
            doc_id = doc_dict.pop("_id")

            # Actualizar documento
            resultado = self.db[coleccion].update_one(
                {"_id": doc_id}, {"$set": doc_dict}
            )

            return resultado.modified_count > 0

        except Exception as e:
            print(f"Error al actualizar documento: {e}")
            return False

    def buscar_por_id(self, modelo_clase, id_documento: str) -> Optional[DocumentoBase]:
        """
        Busca un documento por su ID.

        Args:
            modelo_clase: Clase del modelo de documento
            id_documento: ID del documento a buscar

        Returns:
            Instancia del documento encontrado o None si no existe
        """
        if self.db is None:
            print("No hay conexión activa con MongoDB")
            return None

        try:
            # Obtener colección
            coleccion = getattr(modelo_clase.Config, "collection", None)
            if not coleccion:
                coleccion = modelo_clase.__name__.lower()

            # Buscar documento
            doc = self.db[coleccion].find_one({"_id": id_documento})

            if doc:
                return modelo_clase.from_dict(doc)

            return None

        except Exception as e:
            print(f"Error al buscar documento: {e}")
            return None

    def buscar(
        self, modelo_clase, filtro: Dict[str, Any] = None
    ) -> List[DocumentoBase]:
        """
        Busca documentos que coincidan con un filtro.

        Args:
            modelo_clase: Clase del modelo de documento
            filtro: Filtro de búsqueda (opcional)

        Returns:
            Lista de documentos que coinciden con el filtro
        """
        if self.db is None:
            print("No hay conexión activa con MongoDB")
            return []

        try:
            # Obtener colección
            coleccion = getattr(modelo_clase.Config, "collection", None)
            if not coleccion:
                coleccion = modelo_clase.__name__.lower()

            # Usar filtro vacío si no se proporciona
            if filtro is None:
                filtro = {}

            # Buscar documentos
            docs = list(self.db[coleccion].find(filtro))

            # Convertir resultados a instancias del modelo
            return [modelo_clase.from_dict(doc) for doc in docs]

        except Exception as e:
            print(f"Error al buscar documentos: {e}")
            return []

    def eliminar(self, documento: DocumentoBase) -> bool:
        """
        Elimina un documento de MongoDB.

        Args:
            documento: Instancia de DocumentoBase a eliminar

        Returns:
            True si la eliminación fue exitosa, False en caso contrario
        """
        if self.db is None:
            print("No hay conexión activa con MongoDB")
            return False

        try:
            # Obtener colección
            coleccion = getattr(documento.Config, "collection", None)
            if not coleccion:
                coleccion = documento.__class__.__name__.lower()

            # Eliminar documento
            doc_dict = documento.to_dict()
            resultado = self.db[coleccion].delete_one({"_id": doc_dict.get("_id")})

            return resultado.deleted_count > 0

        except Exception as e:
            print(f"Error al eliminar documento: {e}")
            return False

    def eliminar_por_id(self, modelo_clase, id_documento: str) -> bool:
        """
        Elimina un documento por su ID.

        Args:
            modelo_clase: Clase del modelo de documento
            id_documento: ID del documento a eliminar

        Returns:
            True si la eliminación fue exitosa, False en caso contrario
        """
        if self.db is None:
            print("No hay conexión activa con MongoDB")
            return False

        try:
            # Obtener colección
            coleccion = getattr(modelo_clase.Config, "collection", None)
            if not coleccion:
                coleccion = modelo_clase.__name__.lower()

            # Eliminar documento
            resultado = self.db[coleccion].delete_one({"_id": id_documento})

            return resultado.deleted_count > 0

        except Exception as e:
            print(f"Error al eliminar documento: {e}")
            return False
