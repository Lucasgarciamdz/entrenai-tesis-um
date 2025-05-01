"""
Módulo de clientes para API externas.

Este paquete contiene las clases necesarias para
interactuar con APIs externas, específicamente con Moodle.
"""

from .cliente_moodle import ClienteMoodle
from .extractor_recursos_moodle import ExtractorRecursosMoodle
from .recolector_moodle import RecolectorMoodle

__all__ = ["ClienteMoodle", "ExtractorRecursosMoodle", "RecolectorMoodle"]
