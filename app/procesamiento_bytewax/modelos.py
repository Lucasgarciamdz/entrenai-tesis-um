"""
Modelos de datos para el procesamiento con ByteWax.

Este módulo contiene los modelos Pydantic utilizados para representar
los distintos estados de procesamiento de los documentos de texto.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class ModeloBase(BaseModel):
    """Modelo base para todos los modelos del sistema."""

    id: str
    tipo: str
    fecha_procesamiento: datetime = Field(default_factory=datetime.now)


class ModeloRaw(ModeloBase):
    """
    Modelo para los datos crudos desde MongoDB.

    Representa los datos tal como vienen de MongoDB, sin
    ningún tipo de procesamiento.
    """

    texto: str
    metadatos: Dict[str, Any]
    coleccion: str
    operacion: str


class ModeloLimpio(ModeloBase):
    """
    Modelo para los datos después de la limpieza.

    Representa los datos después de aplicar técnicas de limpieza
    de texto, pero antes de ser troceados.
    """

    texto_limpio: str
    metadatos: Dict[str, Any]
    formato_original: str
    formato_limpio: str = "markdown"


class ModeloTrunk(ModeloBase):
    """
    Modelo para los trunks (fragmentos) de texto.

    Representa un fragmento individual de texto después de
    dividir el documento completo, pero antes de generar embeddings.
    """

    texto: str
    indice: int
    metadatos: Dict[str, Any]
    texto_original_id: str
    contexto: Optional[str] = None


class ModeloEmbedding(ModeloBase):
    """
    Modelo para los trunks con embedding.

    Representa un fragmento de texto con su correspondiente
    embedding vectorial, listo para ser almacenado en una
    base de datos vectorial.
    """

    texto: str
    indice: int
    metadatos: Dict[str, Any]
    texto_original_id: str
    contexto: Optional[str] = None
    embedding: List[float]
    modelo_embedding: str
