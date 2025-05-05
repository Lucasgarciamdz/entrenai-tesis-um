"""
Dispatchers para el procesamiento de documentos en el flujo ByteWax.
"""

from typing import Dict, Any, Optional
import markdown
from loguru import logger
import ollama

from app.config.configuracion import configuracion

class ProcesadorDocumentoDispatcher:
    """Dispatcher para procesar documentos."""
    
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
                
            # Convertir a markdown
            texto_markdown = self._convertir_a_markdown(texto)
            
            # Actualizar documento
            documento["texto"] = texto_markdown
            documento["formato"] = "markdown"
            
            return documento
            
        except Exception as e:
            logger.error(f"Error procesando documento: {e}")
            return None
            
    def _convertir_a_markdown(self, texto: str) -> str:
        """
        Convierte texto plano a markdown.
        
        Args:
            texto: Texto a convertir
            
        Returns:
            Texto en formato markdown
        """
        # Aquí podrías implementar reglas más sofisticadas de conversión
        # Por ahora solo hacemos una conversión básica
        return markdown.markdown(texto)

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
            if not documento or "texto" not in documento:
                return None
                
            texto = documento["texto"]
            
            # Generar embeddings
            if self.usar_ollama:
                embeddings = self._generar_embeddings_ollama(texto)
            else:
                embeddings = self._generar_embeddings_transformers(texto)
                
            if embeddings:
                documento["embeddings"] = embeddings
                return documento
                
            return None
            
        except Exception as e:
            logger.error(f"Error generando embeddings: {e}")
            return None
            
    def _generar_embeddings_ollama(self, texto: str) -> Optional[list]:
        """
        Genera embeddings usando OLLAMA.
        
        Args:
            texto: Texto para generar embeddings
            
        Returns:
            Lista de embeddings o None si hay error
        """
        try:
            # Usar OLLAMA para generar embeddings
            response = ollama.embeddings(
                model=self.modelo,
                prompt=texto
            )
            return response.get("embedding")
            
        except Exception as e:
            logger.error(f"Error con OLLAMA: {e}")
            return None
            
    def _generar_embeddings_transformers(self, texto: str) -> Optional[list]:
        """
        Genera embeddings usando sentence-transformers.
        
        Args:
            texto: Texto para generar embeddings
            
        Returns:
            Lista de embeddings o None si hay error
        """
        try:
            from sentence_transformers import SentenceTransformer
            
            # Cargar modelo
            modelo = SentenceTransformer(self.modelo)
            
            # Generar embeddings
            embeddings = modelo.encode(texto)
            
            return embeddings.tolist()
            
        except Exception as e:
            logger.error(f"Error con sentence-transformers: {e}")
            return None