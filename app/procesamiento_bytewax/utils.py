"""
Utilidades para el procesamiento de texto.

Este módulo proporciona funciones de utilidad para el procesamiento
de texto, incluyendo limpieza, troceado (chunking) y generación de
embeddings.
"""

import re
import unicodedata
import html
import textwrap
import requests
from typing import List, Dict, Any, Tuple

import nltk
from sentence_transformers import SentenceTransformer

from loguru import logger

# Importar ollama (biblioteca oficial)
try:
    import ollama

    OLLAMA_DISPONIBLE = True
except ImportError:
    OLLAMA_DISPONIBLE = False
    logger.warning("Biblioteca Ollama no disponible. Instale con 'pip install ollama'")

# Asegurar que NLTK tenga los recursos necesarios
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", quiet=True)

# Importar sentence_transformers condicionalmente para evitar errores si no está disponible
try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_DISPONIBLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_DISPONIBLE = False
    logger.warning(
        "sentence_transformers no está disponible. Usar OLLAMA o instalar el paquete."
    )

from app.config.configuracion import configuracion


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
    Limpia un texto para su procesamiento.

    Args:
        texto: Texto a limpiar

    Returns:
        Texto limpio
    """
    if not texto:
        return ""

    # Eliminar caracteres especiales y normalizar espacios
    texto_limpio = re.sub(r"\s+", " ", texto)
    texto_limpio = re.sub(r'[^\w\s.,;:!?()[\]{}"\'-]', "", texto_limpio)

    return texto_limpio.strip()


def convertir_a_markdown(texto: str) -> str:
    """
    Convierte un texto plano a formato Markdown.

    Args:
        texto: Texto a convertir

    Returns:
        Texto en formato Markdown
    """
    if not texto:
        return ""

    # Dividir en líneas y párrafos
    lineas = texto.split("\n")
    parrafos = []
    parrafo_actual = []

    for linea in lineas:
        if linea.strip():
            parrafo_actual.append(linea)
        elif parrafo_actual:
            parrafos.append(" ".join(parrafo_actual))
            parrafo_actual = []

    if parrafo_actual:
        parrafos.append(" ".join(parrafo_actual))

    # Intentar identificar títulos y subtítulos
    resultado = []
    for i, parrafo in enumerate(parrafos):
        parrafo = parrafo.strip()

        # Si es un párrafo corto y termina con :, podría ser un título
        if len(parrafo) < 50 and parrafo.endswith(":"):
            resultado.append(f"## {parrafo[:-1]}\n")
        # Si es un párrafo muy corto y es uno de los primeros, podría ser título
        elif len(parrafo) < 30 and i < 2:
            resultado.append(f"# {parrafo}\n")
        # Párrafo normal
        else:
            resultado.append(f"{parrafo}\n\n")

    return "\n".join(resultado)


def dividir_en_trunks(
    texto: str, tam_trunk: int = 512, solapamiento: int = 50
) -> List[str]:
    """
    Divide un texto en trunks (fragmentos) de tamaño similar.

    Args:
        texto: Texto a dividir
        tam_trunk: Tamaño máximo de cada trunk en caracteres
        solapamiento: Número de caracteres de solapamiento entre trunks

    Returns:
        Lista de trunks
    """
    if not texto:
        return []

    # Si el texto es más pequeño que un trunk, devolverlo completo
    if len(texto) <= tam_trunk:
        return [texto]

    # Dividir el texto en párrafos
    parrafos = re.split(r"\n\s*\n", texto)

    trunks = []
    trunk_actual = ""

    for parrafo in parrafos:
        # Si el párrafo es muy grande, dividirlo
        if len(parrafo) > tam_trunk:
            # Dividir en oraciones
            oraciones = re.split(r"(?<=[.!?])\s+", parrafo)

            for oracion in oraciones:
                # Si la oración es muy grande, dividirla en chunks más pequeños
                if len(oracion) > tam_trunk:
                    chunks = textwrap.wrap(oracion, width=tam_trunk)
                    for chunk in chunks:
                        # Si añadir este chunk excede el tamaño, crear nuevo trunk
                        if len(trunk_actual) + len(chunk) > tam_trunk:
                            trunks.append(trunk_actual.strip())
                            # Comenzar nuevo trunk con solapamiento
                            trunk_actual = (
                                (
                                    trunk_actual[-solapamiento:]
                                    if len(trunk_actual) > solapamiento
                                    else ""
                                )
                                + chunk
                                + "\n"
                            )
                        else:
                            trunk_actual += chunk + "\n"
                else:
                    # Si añadir esta oración excede el tamaño, crear nuevo trunk
                    if len(trunk_actual) + len(oracion) > tam_trunk:
                        trunks.append(trunk_actual.strip())
                        # Comenzar nuevo trunk con solapamiento
                        trunk_actual = (
                            (
                                trunk_actual[-solapamiento:]
                                if len(trunk_actual) > solapamiento
                                else ""
                            )
                            + oracion
                            + "\n"
                        )
                    else:
                        trunk_actual += oracion + "\n"
        else:
            # Si añadir este párrafo excede el tamaño, crear nuevo trunk
            if len(trunk_actual) + len(parrafo) > tam_trunk:
                trunks.append(trunk_actual.strip())
                trunk_actual = parrafo + "\n\n"
            else:
                trunk_actual += parrafo + "\n\n"

    # Añadir el último trunk si no está vacío
    if trunk_actual.strip():
        trunks.append(trunk_actual.strip())

    return trunks


def generar_contexto(texto: str, max_longitud: int = 200) -> str:
    """
    Genera un contexto resumido para un texto.

    Args:
        texto: Texto para generar contexto
        max_longitud: Longitud máxima del contexto

    Returns:
        Contexto resumido
    """
    if not texto:
        return ""

    # Eliminar caracteres de nueva línea
    texto_plano = re.sub(r"\s+", " ", texto)

    # Truncar a longitud máxima
    if len(texto_plano) > max_longitud:
        contexto = texto_plano[:max_longitud] + "..."
    else:
        contexto = texto_plano

    return contexto


def generar_embedding(
    texto: str, modelo_nombre: str = "all-MiniLM-L6-v2", usar_ollama: bool = False
) -> List[float]:
    """
    Genera un embedding vectorial para un texto dado.

    Args:
        texto: Texto para el que generar el embedding
        modelo_nombre: Nombre del modelo de embedding a utilizar
        usar_ollama: Si es True, usa la biblioteca Ollama para generar embeddings.
                    Si es False, usa sentence-transformers local.

    Returns:
        Vector de embedding o lista vacía en caso de error
    """
    try:
        # Validar texto
        if not texto or not texto.strip():
            logger.warning("Texto vacío para generar embedding")
            return []

        # Si el texto es muy largo, truncar para evitar problemas
        texto_procesado = texto[:8192] if len(texto) > 8192 else texto

        # Decidir método de embedding
        if usar_ollama:
            return _generar_embedding_ollama(texto_procesado, modelo_nombre)
        else:
            return _generar_embedding_local(texto_procesado, modelo_nombre)

    except Exception as e:
        logger.error(f"Error al generar embedding: {e}")
        return []


def _generar_embedding_ollama(texto: str, modelo_nombre: str) -> List[float]:
    """
    Genera un embedding utilizando OLLAMA.

    Args:
        texto: Texto para generar el embedding
        modelo_nombre: Nombre del modelo en OLLAMA

    Returns:
        Vector de embedding o lista vacía en caso de error
    """
    try:
        # Validar que la biblioteca Ollama esté disponible
        if not OLLAMA_DISPONIBLE:
            logger.error(
                "No se puede generar embedding: biblioteca Ollama no disponible"
            )
            return []

        logger.debug(
            f"Generando embedding con biblioteca Ollama para modelo '{modelo_nombre}'"
        )

        # Generar embedding usando la biblioteca Ollama
        try:
            # Llamar al método embed de la biblioteca Ollama
            resultado = ollama.embed(model=modelo_nombre, input=texto)

            # Extraer embedding de la respuesta
            if "embeddings" in resultado:
                embedding = resultado["embeddings"]
                logger.debug(
                    f"Embedding generado correctamente con Ollama (dimensión: {len(embedding)})"
                )
                return embedding
            elif "embedding" in resultado:
                embedding = resultado["embedding"]
                logger.debug(
                    f"Embedding generado correctamente con Ollama (dimensión: {len(embedding)})"
                )
                return embedding
            else:
                logger.error(f"Respuesta de Ollama no contiene embedding: {resultado}")
                return []

        except Exception as e:
            logger.error(f"Error al llamar a la API de Ollama: {e}")

            # Fallback: intentar con requests directo si hay error en la biblioteca
            if not hasattr(_generar_embedding_ollama, "fallback_warning_shown"):
                logger.warning(
                    "Utilizando método alternativo (requests) para comunicarse con Ollama"
                )
                _generar_embedding_ollama.fallback_warning_shown = True

            # Obtener URL de OLLAMA (con valor por defecto)
            url_ollama = configuracion.obtener(
                "OLLAMA_URL", "http://localhost:11434/api/embeddings"
            )

            # Preparar datos para la petición
            datos = {"model": modelo_nombre, "prompt": texto}

            # Realizar la petición a OLLAMA
            respuesta = requests.post(
                url_ollama,
                json=datos,
                headers={"Content-Type": "application/json"},
                timeout=30,  # 30 segundos de timeout
            )

            # Verificar respuesta
            if respuesta.status_code != 200:
                logger.error(
                    f"Error en la petición a OLLAMA: {respuesta.status_code} - {respuesta.text}"
                )
                return []

            # Extraer embedding de la respuesta
            resultado = respuesta.json()

            if "embedding" not in resultado:
                logger.error(f"Respuesta de OLLAMA no contiene embedding: {resultado}")
                return []

            embedding = resultado["embedding"]
            logger.debug(
                f"Embedding generado con método alternativo (dimensión: {len(embedding)})"
            )
            return embedding

    except Exception as e:
        logger.error(f"Error al generar embedding con OLLAMA: {e}")
        return []


def _generar_embedding_local(texto: str, modelo_nombre: str) -> List[float]:
    """
    Genera un embedding utilizando sentence-transformers local.

    Args:
        texto: Texto para generar el embedding
        modelo_nombre: Nombre del modelo de sentence-transformers

    Returns:
        Vector de embedding o lista vacía en caso de error
    """
    try:
        # Verificar si sentence-transformers está disponible
        if not SENTENCE_TRANSFORMERS_DISPONIBLE:
            logger.error(
                "No se puede generar embedding local: sentence-transformers no está disponible"
            )
            return []

        logger.debug(f"Generando embedding local con modelo '{modelo_nombre}'")

        # Variables para cache de modelos
        global _modelos_cache
        if "_modelos_cache" not in globals():
            _modelos_cache = {}

        # Cargar modelo (o usar desde cache)
        if modelo_nombre not in _modelos_cache:
            logger.info(f"Cargando modelo '{modelo_nombre}' (primera vez)")
            _modelos_cache[modelo_nombre] = SentenceTransformer(modelo_nombre)

        modelo = _modelos_cache[modelo_nombre]

        # Generar embedding
        embedding = modelo.encode(texto).tolist()
        logger.debug(f"Embedding generado correctamente (dimensión: {len(embedding)})")
        return embedding

    except Exception as e:
        logger.error(f"Error al generar embedding local: {e}")
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
