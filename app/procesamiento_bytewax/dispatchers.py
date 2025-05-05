"""
Dispatchers para el procesamiento de documentos en el flujo ByteWax.
"""

from typing import Dict, Any, Optional, List
import json
import markdown
from loguru import logger
import ollama

from app.config.configuracion import configuracion
from app.procesamiento_bytewax.utils import (
    limpiar_texto,
    convertir_a_markdown,
    dividir_en_chunks,
    generar_contexto,
    generar_embedding,
    procesar_documento_raw,
    procesar_documento_limpio,
    procesar_documento_chunks,
    procesar_documento_embedding
)

class ProcesadorDocumentoDispatcher:
    """Dispatcher para procesar documentos."""
    
    def __init__(self):
        """Inicializa el dispatcher."""
        self.usar_ollama = configuracion.obtener("USAR_OLLAMA", "false").lower() == "true"
        self.modelo_texto = configuracion.obtener("MODELO_TEXTO", "llama3")
        self.tam_chunk = int(configuracion.obtener("TAMANO_CHUNK", "1000"))
        self.solapamiento = int(configuracion.obtener("SOLAPAMIENTO_CHUNK", "200"))
        
    def procesar(self, mensaje: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Procesa un documento convirtiéndolo a markdown y limpiándolo.
        
        Args:
            mensaje: Mensaje con el documento a procesar
            
        Returns:
            Documento procesado o None si hay error
        """
        try:
            # Extraer documento del mensaje CDC
            if not mensaje.get("fullDocument"):
                logger.warning("Mensaje no contiene documento")
                return None
                
            documento = mensaje["fullDocument"]
            
            # Extraer texto
            texto = documento.get("texto", "")
            if not texto:
                logger.warning("Documento no contiene texto")
                return None
            
            # Convertir a documento raw
            doc_raw = procesar_documento_raw(documento)
            if not doc_raw:
                return None
                
            # Procesar y limpiar el documento
            doc_limpio = procesar_documento_limpio(doc_raw)
            if not doc_limpio:
                return None
                
            # Transformar a markdown mejorado con Ollama si está habilitado
            if self.usar_ollama:
                texto_mejorado = self._mejorar_texto_con_ollama(doc_limpio.texto)
                if texto_mejorado:
                    doc_limpio.texto = texto_mejorado
            
            # Dividir en chunks
            chunks = procesar_documento_chunks(doc_limpio)
            if not chunks:
                # Si no hay chunks, devolver documento completo
                documento["texto"] = doc_limpio.texto
                documento["formato"] = "markdown"
                return documento
                
            # Crear estructura de respuesta con document limpio y sus chunks
            resultado = {
                "id": doc_limpio.id,
                "id_original": doc_limpio.id_original,
                "texto": doc_limpio.texto,
                "formato": "markdown",
                "chunks": [
                    {
                        "id": chunk.id,
                        "texto": chunk.texto,
                        "indice": chunk.indice_chunk,
                        "total": chunk.total_chunks,
                        "contexto": chunk.contexto
                    } for chunk in chunks
                ],
                "metadatos": doc_limpio.metadatos
            }
            
            # Añadir campos originales al resultado
            for clave, valor in documento.items():
                if clave not in resultado and clave != "texto":
                    resultado[clave] = valor
            
            return resultado
            
        except Exception as e:
            logger.error(f"Error procesando documento: {e}")
            return None
            
    def _mejorar_texto_con_ollama(self, texto: str) -> Optional[str]:
        """
        Mejora el texto convirtiéndolo a markdown usando Ollama.
        
        Args:
            texto: Texto a mejorar
            
        Returns:
            Texto mejorado en formato markdown o None si hay error
        """
        try:
            # Limitar texto para prevenir problemas con modelos
            texto_limitado = texto[:50000] if len(texto) > 50000 else texto
            
            # Prompt para la transformación
            prompt = f"""
            Tu tarea es transformar el siguiente texto a formato markdown bien estructurado.
            Mantén todo el contenido original, pero mejora el formato para hacerlo más legible.
            
            - Agrega encabezados adecuados (##, ###, etc.)
            - Crea listas con viñetas donde sea apropiado
            - Identifica y formatea bloques de código
            - Respeta las fórmulas matemáticas si existen
            - Preserva la estructura del documento
            
            IMPORTANTE: Mantén todo el contenido original sin agregar ni quitar información.
            No inventes ni añadas contenido que no esté presente.
            
            TEXTO:
            {texto_limitado}
            
            MARKDOWN:
            """
            
            # Llamar a Ollama para mejorar el texto
            respuesta = ollama.chat(
                model=self.modelo_texto,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                stream=False
            )
            
            if respuesta and "message" in respuesta and "content" in respuesta["message"]:
                texto_mejorado = respuesta["message"]["content"]
                logger.info(f"Texto mejorado con Ollama (modelo: {self.modelo_texto})")
                return texto_mejorado
            else:
                logger.warning("Respuesta vacía o inválida de Ollama")
                return None
                
        except Exception as e:
            logger.error(f"Error al mejorar texto con Ollama: {e}")
            return None

class GeneradorEmbeddingsDispatcher:
    """Dispatcher para generar embeddings."""
    
    def __init__(self):
        """Inicializa el dispatcher."""
        self.modelo = configuracion.obtener("MODELO_EMBEDDING", "all-MiniLM-L6-v2")
        self.usar_ollama = configuracion.obtener("USAR_OLLAMA", "false").lower() == "true"
        
    def procesar(self, documento: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Genera embeddings para un documento.
        
        Args:
            documento: Documento a procesar
            
        Returns:
            Documento con embeddings o None si hay error
        """
        try:
            if not documento:
                return None
                
            # Verificar si el documento tiene chunks
            if "chunks" in documento and documento["chunks"]:
                # Procesar cada chunk
                for i, chunk in enumerate(documento["chunks"]):
                    # Generar embedding para el chunk
                    embedding = self._generar_embedding(chunk["texto"])
                    if embedding:
                        documento["chunks"][i]["embedding"] = embedding
                        documento["chunks"][i]["modelo_embedding"] = self.modelo
                
                # Añadir bandera de procesamiento completo
                documento["embeddings_generados"] = True
                return documento
            else:
                # Documento sin chunks, procesar texto completo
                texto = documento.get("texto", "")
                if not texto:
                    logger.warning("Documento sin texto para embedding")
                    return None
                    
                # Generar embedding
                embedding = self._generar_embedding(texto)
                if embedding:
                    documento["embedding"] = embedding
                    documento["modelo_embedding"] = self.modelo
                    documento["embeddings_generados"] = True
                    return documento
                
            return None
            
        except Exception as e:
            logger.error(f"Error generando embeddings: {e}")
            return None
            
    def _generar_embedding(self, texto: str) -> Optional[List[float]]:
        """
        Genera un embedding para el texto dado.
        
        Args:
            texto: Texto para generar embedding
            
        Returns:
            Vector de embedding o None si hay error
        """
        return generar_embedding(texto, self.modelo, self.usar_ollama)