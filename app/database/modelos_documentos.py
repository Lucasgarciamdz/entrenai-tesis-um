"""
Modelos de documentos para MongoDB.

Este módulo define las clases de documentos que representan
la estructura de datos en la base de datos MongoDB.
"""

import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentoBase(BaseModel):
    """Modelo base para todos los documentos en MongoDB."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fecha_creacion: datetime = Field(default_factory=datetime.now)
    fecha_actualizacion: Optional[datetime] = None

    class Config:
        """Configuración para el modelo Pydantic."""

        populate_by_name = True
        arbitrary_types_allowed = True

    def to_dict(self) -> Dict[str, Any]:
        """
        Convierte el documento a un diccionario para MongoDB.

        Returns:
            Diccionario con los datos del documento
        """
        data = self.dict(by_alias=True)
        # Convertir id a _id para MongoDB
        if "id" in data:
            data["_id"] = data.pop("id")
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """
        Crea una instancia del documento a partir de un diccionario.

        Args:
            data: Diccionario con los datos del documento

        Returns:
            Instancia del documento
        """
        # Convertir _id a id desde MongoDB
        if "_id" in data and "id" not in data:
            data["id"] = str(data.pop("_id"))
        return cls(**data)


class Curso(DocumentoBase):
    """Modelo de documento para representar un curso."""

    id_moodle: int
    nombre: str
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    fecha_inicio: Optional[datetime] = None
    profesor: Optional[str] = None
    categorias: List[str] = []

    class Config:
        collection = "cursos"


class ContenidoTexto(DocumentoBase):
    """Modelo de documento para contenido de texto extraído."""

    id_curso: int
    nombre_curso: str
    ruta_archivo: str
    nombre_archivo: str
    tipo_archivo: str
    texto: str
    metadatos: Dict[str, Any] = {}
    formato: str = "txt"
    tamaño: Optional[int] = None

    class Config:
        collection = "contenidos"


class DocumentoPDF(ContenidoTexto):
    """Modelo específico para documentos PDF."""

    tipo_archivo: str = "pdf"
    tiene_imagenes: bool = False
    total_paginas: int = 0
    imagenes_extraidas: List[str] = []
    procesado_con_ocr: bool = False
    contiene_formulas: bool = False

    class Config:
        collection = "contenidos"


class DocumentoHTML(ContenidoTexto):
    """Modelo específico para documentos HTML."""

    tipo_archivo: str = "html"
    url_origen: Optional[str] = None
    enlaces_externos: List[str] = []

    class Config:
        collection = "contenidos"
