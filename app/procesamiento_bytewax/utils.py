"""
Utilidades para el procesamiento de texto.

Este módulo proporciona funciones de utilidad para el procesamiento
de texto, incluyendo limpieza, troceado (chunking) y generación de
embeddings.
"""

import re
import unicodedata
import html
from typing import List, Dict, Any, Tuple

import nltk
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter,
    SentenceTransformersTokenTextSplitter,
)
from sentence_transformers import SentenceTransformer

from loguru import logger

# Asegurar que NLTK tenga los recursos necesarios
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", quiet=True)


def quitar_saltos_extra(texto: str) -> str:
    """
    Elimina saltos de línea consecutivos y los reemplaza por uno solo.

    Args:
        texto: Texto a procesar

    Returns:
        Texto con saltos de línea normalizados
    """
    return re.sub(r"\n{3,}", "\n\n", texto)


def quitar_espacios_extra(texto: str) -> str:
    """
    Elimina espacios consecutivos y los reemplaza por uno solo.

    Args:
        texto: Texto a procesar

    Returns:
        Texto con espacios normalizados
    """
    return re.sub(r" {2,}", " ", texto)


def normalizar_unicode(texto: str) -> str:
    """
    Normaliza caracteres Unicode a su forma canónica.

    Args:
        texto: Texto a normalizar

    Returns:
        Texto con caracteres Unicode normalizados
    """
    return unicodedata.normalize("NFKC", texto)


def escapar_html(texto: str) -> str:
    """
    Convierte entidades HTML a sus equivalentes Unicode.

    Args:
        texto: Texto a procesar

    Returns:
        Texto con entidades HTML convertidas
    """
    return html.unescape(texto)


def limpiar_texto(texto: str) -> str:
    """
    Aplica varias técnicas de limpieza al texto.

    Args:
        texto: Texto a limpiar

    Returns:
        Texto limpio
    """
    # Verificar que tenemos texto
    if not texto:
        return ""

    # Secuencia de limpieza
    texto = escapar_html(texto)
    texto = normalizar_unicode(texto)
    texto = quitar_espacios_extra(texto)
    texto = quitar_saltos_extra(texto)

    # Eliminar URLs
    texto = re.sub(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
        "",
        texto,
    )

    # Eliminar caracteres especiales no deseados
    texto = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", texto)

    return texto.strip()


def convertir_a_markdown(texto: str) -> str:
    """
    Convierte texto plano a formato Markdown estructurado.

    Args:
        texto: Texto a convertir

    Returns:
        Texto en formato Markdown
    """
    # Dividir en párrafos
    parrafos = re.split(r"\n{2,}", texto)

    # Detectar títulos y formatearlos
    texto_markdown = []
    for p in parrafos:
        # Intentar detectar títulos
        if len(p.strip()) < 100 and not p.endswith("."):
            # Posible título
            if p.isupper():
                # Título en mayúsculas, convertir a título nivel 2
                texto_markdown.append(f"## {p.title()}")
            else:
                # Posible subtítulo
                texto_markdown.append(f"### {p}")
        else:
            # Agregar como párrafo normal
            texto_markdown.append(p)

    return "\n\n".join(texto_markdown)


def dividir_en_trunks(
    texto: str, tamaño_chunk: int = 512, solapamiento: int = 50
) -> List[str]:
    """
    Divide el texto en trunks (fragmentos) para procesamiento RAG.

    Args:
        texto: Texto a dividir
        tamaño_chunk: Tamaño objetivo de cada chunk en tokens
        solapamiento: Número de tokens de solapamiento entre chunks

    Returns:
        Lista de fragmentos de texto
    """
    # Primero dividimos por caracteres para respetar unidades semánticas
    splitter_caracteres = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " ", ""],
        chunk_size=tamaño_chunk * 4,  # Aproximación: 4 caracteres por token
        chunk_overlap=solapamiento * 4,
        length_function=len,
    )

    # Luego dividimos por tokens para un control más preciso del tamaño
    splitter_tokens = SentenceTransformersTokenTextSplitter(
        model_name="all-MiniLM-L6-v2",
        tokens_per_chunk=tamaño_chunk,
        chunk_overlap=solapamiento,
    )

    # Aplicar la primera división
    chunks_iniciales = splitter_caracteres.split_text(texto)

    # Aplicar la segunda división
    chunks_finales = []
    for chunk in chunks_iniciales:
        chunks_finales.extend(splitter_tokens.split_text(chunk))

    return chunks_finales


def generar_contexto(texto: str, modelo_llm=None) -> str:
    """
    Genera una descripción de contexto para un fragmento de texto.

    Este contexto se utilizará para enriquecer los fragmentos en el
    sistema de RAG, implementando Context Augmented Retrieval.

    Args:
        texto: Texto para el que generar contexto
        modelo_llm: Modelo de lenguaje opcional para mejorar el contexto

    Returns:
        Texto de contexto
    """
    # Versión simple de generación de contexto
    # En producción, esto usaría un modelo LLM
    resumen = texto[:200] + "..." if len(texto) > 200 else texto

    # Detectar posible tema
    palabras = nltk.word_tokenize(texto.lower())
    freq_dist = nltk.FreqDist(palabras)

    # Filtrar palabras comunes
    palabras_stop = set(
        [
            "el",
            "la",
            "los",
            "las",
            "un",
            "una",
            "unos",
            "unas",
            "y",
            "o",
            "a",
            "ante",
            "bajo",
            "con",
            "de",
            "desde",
            "en",
            "entre",
            "hacia",
            "hasta",
            "para",
            "por",
            "según",
            "sin",
            "sobre",
            "tras",
        ]
    )

    palabras_clave = [
        w for w, f in freq_dist.most_common(10) if w not in palabras_stop and len(w) > 3
    ]

    # Generar contexto básico
    return f"Este fragmento trata sobre: {', '.join(palabras_clave[:5])}. {resumen}"


def generar_embedding(
    texto: str, modelo_nombre: str = "all-MiniLM-L6-v2", usar_ollama: bool = False
) -> List[float]:
    """
    Genera un embedding vectorial para un texto dado.

    Args:
        texto: Texto para el que generar el embedding
        modelo_nombre: Nombre del modelo de embedding a utilizar
        usar_ollama: Si es True, usa OLLAMA para generar embeddings.
                    Si es False, usa sentence-transformers local.

    Returns:
        Vector de embedding
    """
    try:
        if not texto.strip():
            logger.warning("Texto vacío para generar embedding")
            return []

        # Si el texto es muy largo, truncar para evitar problemas
        texto_procesado = texto[:8192] if len(texto) > 8192 else texto

        if usar_ollama:
            try:
                import requests
                import json

                # Configuración para OLLAMA
                ollama_url = "http://localhost:11434/api/embeddings"

                # Preparar la solicitud
                payload = {"model": modelo_nombre, "prompt": texto_procesado}

                # Enviar la solicitud a OLLAMA
                response = requests.post(
                    ollama_url,
                    data=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )

                # Verificar si la respuesta es exitosa
                if response.status_code == 200:
                    result = response.json()
                    embedding = result.get("embedding", [])

                    # Verificar que el embedding tiene datos
                    if not embedding or len(embedding) < 10:
                        logger.error(
                            f"OLLAMA devolvió un embedding vacío o muy pequeño: {embedding}"
                        )
                        raise ValueError("Embedding vacío o inválido de OLLAMA")

                    logger.info(
                        f"Embedding generado con OLLAMA (dimensiones: {len(embedding)})"
                    )
                    return embedding
                else:
                    logger.error(
                        f"Error de OLLAMA: {response.status_code} - {response.text}"
                    )
                    raise ValueError(
                        f"Error al generar embedding con OLLAMA: {response.text}"
                    )

            except ImportError:
                logger.error(
                    "No se pudo importar el módulo 'requests'. Usando sentence-transformers como fallback."
                )
                # Si fallan las importaciones, usar sentence-transformers como fallback
            except Exception as e:
                logger.error(
                    f"Error al usar OLLAMA: {e}. Usando sentence-transformers como fallback."
                )
                # Si falla OLLAMA, usar sentence-transformers como fallback

        # Usar sentence-transformers (opción por defecto o fallback)
        modelo = SentenceTransformer(modelo_nombre)
        embedding = modelo.encode(texto_procesado, convert_to_tensor=False).tolist()

        logger.info(
            f"Embedding generado con sentence-transformers (dimensiones: {len(embedding)})"
        )
        return embedding

    except Exception as e:
        logger.error(f"Error al generar embedding: {e}")
        # Devolver un vector vacío si hay error
        return []


def procesar_texto_completo(texto: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Procesa un texto completo: limpia, divide en trunks, genera contexto y embeddings.

    Args:
        texto: Texto a procesar

    Returns:
        Tupla con (texto_limpio_markdown, lista_trunks_con_embeddings)
    """
    # Limpiar texto
    texto_limpio = limpiar_texto(texto)

    # Convertir a markdown
    texto_markdown = convertir_a_markdown(texto_limpio)

    # Dividir en trunks
    trunks = dividir_en_trunks(texto_markdown)

    # Procesar cada trunk
    trunks_procesados = []
    for i, trunk in enumerate(trunks):
        # Generar contexto
        contexto = generar_contexto(trunk)

        # Generar embedding
        embedding = generar_embedding(trunk)

        # Guardar información del trunk
        trunks_procesados.append(
            {
                "indice": i,
                "texto": trunk,
                "contexto": contexto,
                "embedding": embedding,
            }
        )

    return texto_markdown, trunks_procesados
