"""
Modelos Pydantic para el procesamiento de documentos con ByteWax.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class ModeloBase(BaseModel):
    """Modelo base para todos los documentos."""

    id: str = Field(..., description="ID único del documento")
    id_original: Optional[str] = Field(None, description="ID original en MongoDB")
    metadatos: Dict[str, Any] = Field(
        default_factory=dict, description="Metadatos adicionales"
    )


class DocumentoRaw(ModeloBase):
    """Documento en su estado inicial."""

    texto: str = Field(..., description="Texto original del documento")
    tipo_archivo: str = Field(..., description="Tipo de archivo (pdf, txt, html, etc)")
    nombre_archivo: str = Field(..., description="Nombre del archivo")
    id_curso: Optional[int] = Field(None, description="ID del curso en Moodle")
    nombre_curso: Optional[str] = Field(None, description="Nombre del curso en Moodle")
    ruta_archivo: Optional[str] = Field(None, description="Ruta al archivo original")
    fecha_procesamiento: datetime = Field(default_factory=datetime.now)


class DocumentoLimpio(ModeloBase):
    """Documento después de la limpieza y normalización."""

    texto: str = Field(..., description="Texto limpio y normalizado")
    texto_original: Optional[str] = Field(
        None, description="Texto original antes de limpieza"
    )
    tipo_contenido: Optional[str] = Field(
        None, description="Tipo de contenido detectado"
    )
    contiene_formulas: bool = Field(
        default=False, description="Si contiene fórmulas matemáticas"
    )
    contiene_codigo: bool = Field(
        default=False, description="Si contiene bloques de código"
    )


class DocumentoChunk(ModeloBase):
    """Chunk de documento después de la segmentación."""

    texto: str = Field(..., description="Texto del chunk")
    indice_chunk: int = Field(..., description="Índice del chunk en el documento")
    total_chunks: int = Field(..., description="Total de chunks del documento")
    contexto: str = Field(..., description="Contexto o resumen del chunk")
    solapamiento: Optional[int] = Field(None, description="Caracteres de solapamiento")


class DocumentoEmbedding(ModeloBase):
    """Documento con embedding generado."""

    texto: str = Field(..., description="Texto del chunk")
    embedding: List[float] = Field(..., description="Vector de embedding")
    modelo_embedding: str = Field(..., description="Modelo usado para embedding")
    dimension: int = Field(..., description="Dimensión del vector de embedding")
    coleccion: str = Field(..., description="Colección en Qdrant donde se almacenará")
