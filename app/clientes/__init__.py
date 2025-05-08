"""
Módulo de Clientes.

Este paquete contiene las clases cliente para interactuar con servicios externos
como Moodle, N8N, etc.
"""

from .cliente_moodle import ClienteMoodle
from .extractor_recursos_moodle import ExtractorRecursosMoodle
from .recolector_moodle import RecolectorMoodle
from .cliente_n8n import ClienteN8N  # Añadir el nuevo cliente

__all__ = [
    "ClienteMoodle",
    "ExtractorRecursosMoodle",
    "RecolectorMoodle",
    "ClienteN8N",  # Exportar el nuevo cliente
]
