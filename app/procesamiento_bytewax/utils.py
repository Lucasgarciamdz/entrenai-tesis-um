"""
Utilidades para el procesamiento de documentos con ByteWax.
"""

import re
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from loguru import logger
import markdown
import nltk
from nltk.tokenize import sent_tokenize
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.config.configuracion import configuracion
from app.procesamiento_bytewax.modelos import (
    DocumentoRaw,
    DocumentoLimpio,
    DocumentoChunk,
    DocumentoEmbedding,
)

# Descargar recursos de NLTK necesarios
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

def limpiar_texto(texto: str) -> str:
    """
    Limpia y normaliza el texto.
    
    Args:
        texto: Texto a limpiar
        
    Returns:
        Texto limpiado y normalizado
    """
    if not texto:
        return ""
        
    # Normalizar espacios en blanco
    texto = re.sub(r'\s+', ' ', texto)
    texto = texto.strip()
    
    # Normalizar saltos de línea
    texto = re.sub(r'\n\s*\n', '\n\n', texto)
    
    # Normalizar caracteres especiales
    texto = texto.replace('\u200b', '')  # Eliminar zero-width space
    texto = texto.replace('\xa0', ' ')   # Reemplazar non-breaking space
    
    return texto

def convertir_a_markdown(texto: str) -> str:
    """
    Convierte texto plano a formato Markdown.
    
    Args:
        texto: Texto a convertir
        
    Returns:
        Texto en formato Markdown
    """
    if not texto:
        return ""
        
    # Detectar y preservar bloques de código
    texto = re.sub(r'```.*?\n(.*?)```', lambda m: '```\n' + m.group(1) + '```', texto, flags=re.DOTALL)
    
    # Detectar y preservar fórmulas matemáticas
    texto = re.sub(r'\$(.*?)\$', r'$\1$', texto)
    texto = re.sub(r'\$\$(.*?)\$\$', r'$$\1$$', texto, flags=re.DOTALL)
    
    # Convertir listas
    texto = re.sub(r'^\s*[-*]\s', '* ', texto, flags=re.MULTILINE)
    texto = re.sub(r'^\s*(\d+)[.)]\s', r'\1. ', texto, flags=re.MULTILINE)
    
    # Convertir títulos
    texto = re.sub(r'^([A-Za-z0-9].*)\n={3,}$', r'# \1', texto, flags=re.MULTILINE)
    texto = re.sub(r'^([A-Za-z0-9].*)\n-{3,}$', r'## \1', texto, flags=re.MULTILINE)
    
    # Convertir énfasis
    texto = re.sub(r'(?<![\w*])\*(\w[^*]*\w)\*(?![\w*])', r'*\1*', texto)
    texto = re.sub(r'(?<![\w_])_(\w[^_]*\w)_(?![\w_])', r'_\1_', texto)
    
    return texto

def dividir_en_chunks(texto: str, tam_chunk: int = 1000, solapamiento: int = 200) -> List[str]:
    """
    Divide el texto en chunks más pequeños.
    
    Args:
        texto: Texto a dividir
        tam_chunk: Tamaño aproximado de cada chunk
        solapamiento: Cantidad de caracteres de solapamiento entre chunks
        
    Returns:
        Lista de chunks de texto
    """
    if not texto:
        return []
        
    # Usar LangChain para dividir el texto
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=tam_chunk,
        chunk_overlap=solapamiento,
        length_function=len,
        separators=["\n\n", "\n", " ", ""]
    )
    
    chunks = splitter.split_text(texto)
    return chunks

def generar_contexto(texto: str, max_len: int = 100) -> str:
    """
    Genera un resumen o contexto para un fragmento de texto.
    
    Args:
        texto: Texto del que generar contexto
        max_len: Longitud máxima del contexto
        
    Returns:
        Contexto o resumen del texto
    """
    if not texto:
        return ""
        
    # Obtener primera oración
    oraciones = sent_tokenize(texto)
    if not oraciones:
        return texto[:max_len] + "..." if len(texto) > max_len else texto
        
    primera_oracion = oraciones[0]
    if len(primera_oracion) <= max_len:
        return primera_oracion
        
    return primera_oracion[:max_len] + "..."

def generar_embedding(texto: str, modelo_nombre: str = "all-MiniLM-L6-v2", usar_ollama: bool = False) -> Optional[List[float]]:
    """
    Genera un embedding para el texto dado.
    
    Args:
        texto: Texto a vectorizar
        modelo_nombre: Nombre del modelo a usar
        usar_ollama: Si usar OLLAMA en lugar de sentence-transformers
        
    Returns:
        Vector de embedding o None si hay error
    """
    if not texto:
        return None
        
    try:
        if usar_ollama:
            import ollama
            # Generar embedding con OLLAMA
            respuesta = ollama.embeddings(
                model=modelo_nombre,
                prompt=texto
            )
            return respuesta.get('embedding')
        else:
            from sentence_transformers import SentenceTransformer
            # Generar embedding con sentence-transformers
            modelo = SentenceTransformer(modelo_nombre)
            embedding = modelo.encode(texto, convert_to_tensor=False)
            return embedding.tolist()
            
    except Exception as e:
        logger.error(f"Error al generar embedding: {e}")
        return None

def procesar_documento_raw(documento: Dict[str, Any]) -> Optional[DocumentoRaw]:
    """
    Procesa un documento raw desde MongoDB/RabbitMQ.
    
    Args:
        documento: Documento en formato diccionario
        
    Returns:
        DocumentoRaw procesado o None si hay error
    """
    try:
        # Extraer campos básicos
        id_doc = str(documento.get("_id", ""))
        texto = documento.get("texto", "")
        
        if not texto:
            logger.warning(f"Documento {id_doc} sin texto, ignorando")
            return None
            
        # Crear documento raw
        doc_raw = DocumentoRaw(
            id=id_doc,
            id_original=id_doc,
            texto=texto,
            tipo_archivo=documento.get("tipo_archivo", "txt"),
            nombre_archivo=documento.get("nombre_archivo", "documento.txt"),
            id_curso=documento.get("id_curso"),
            nombre_curso=documento.get("nombre_curso", ""),
            ruta_archivo=documento.get("ruta_archivo", ""),
            metadatos=documento.get("metadatos", {})
        )
        
        return doc_raw
        
    except Exception as e:
        logger.error(f"Error procesando documento raw: {e}")
        return None

def procesar_documento_limpio(doc_raw: DocumentoRaw) -> Optional[DocumentoLimpio]:
    """
    Limpia y normaliza un documento raw.
    
    Args:
        doc_raw: Documento raw a procesar
        
    Returns:
        DocumentoLimpio procesado o None si hay error
    """
    try:
        # Limpiar texto
        texto_limpio = limpiar_texto(doc_raw.texto)
        if not texto_limpio:
            logger.warning(f"Documento {doc_raw.id} quedó vacío después de limpieza")
            return None
            
        # Convertir a markdown
        texto_markdown = convertir_a_markdown(texto_limpio)
        
        # Detectar características especiales
        contiene_formulas = bool(re.search(r'\$.*?\$', texto_markdown))
        contiene_codigo = bool(re.search(r'```.*?```', texto_markdown, re.DOTALL))
        
        # Crear documento limpio
        doc_limpio = DocumentoLimpio(
            id=f"{doc_raw.id}_limpio",
            id_original=doc_raw.id,
            texto=texto_markdown,
            texto_original=doc_raw.texto,
            tipo_contenido="markdown",
            contiene_formulas=contiene_formulas,
            contiene_codigo=contiene_codigo,
            metadatos=doc_raw.metadatos
        )
        
        return doc_limpio
        
    except Exception as e:
        logger.error(f"Error procesando documento limpio: {e}")
        return None

def procesar_documento_chunks(doc_limpio: DocumentoLimpio) -> List[DocumentoChunk]:
    """
    Divide un documento limpio en chunks.
    
    Args:
        doc_limpio: Documento limpio a procesar
        
    Returns:
        Lista de DocumentoChunk procesados
    """
    try:
        # Dividir en chunks
        chunks = dividir_en_chunks(doc_limpio.texto)
        if not chunks:
            logger.warning(f"No se generaron chunks para documento {doc_limpio.id}")
            return []
            
        # Crear documentos chunk
        docs_chunk = []
        for i, chunk in enumerate(chunks):
            # Generar contexto
            contexto = generar_contexto(chunk)
            
            # Crear documento chunk
            doc_chunk = DocumentoChunk(
                id=f"{doc_limpio.id}_chunk_{i}",
                id_original=doc_limpio.id_original,
                texto=chunk,
                indice_chunk=i,
                total_chunks=len(chunks),
                contexto=contexto,
                solapamiento=200,  # Valor por defecto
                metadatos=doc_limpio.metadatos
            )
            docs_chunk.append(doc_chunk)
            
        return docs_chunk
        
    except Exception as e:
        logger.error(f"Error procesando chunks: {e}")
        return []

def procesar_documento_embedding(doc_chunk: DocumentoChunk, modelo_nombre: str, usar_ollama: bool = False) -> Optional[DocumentoEmbedding]:
    """
    Genera embedding para un chunk de documento.
    
    Args:
        doc_chunk: Documento chunk a procesar
        modelo_nombre: Nombre del modelo de embedding
        usar_ollama: Si usar OLLAMA en lugar de sentence-transformers
        
    Returns:
        DocumentoEmbedding procesado o None si hay error
    """
    try:
        # Generar embedding
        embedding = generar_embedding(
            texto=doc_chunk.texto,
            modelo_nombre=modelo_nombre,
            usar_ollama=usar_ollama
        )
        
        if not embedding:
            logger.warning(f"No se pudo generar embedding para chunk {doc_chunk.id}")
            return None
            
        # Determinar colección
        id_curso = doc_chunk.metadatos.get("id_curso")
        coleccion = f"curso_{id_curso}" if id_curso else "general"
        
        # Crear documento con embedding
        doc_embedding = DocumentoEmbedding(
            id=f"{doc_chunk.id}_emb",
            id_original=doc_chunk.id_original,
            texto=doc_chunk.texto,
            embedding=embedding,
            modelo_embedding=modelo_nombre,
            dimension=len(embedding),
            coleccion=coleccion,
            metadatos=doc_chunk.metadatos
        )
        
        return doc_embedding
        
    except Exception as e:
        logger.error(f"Error procesando embedding: {e}")
        return None
