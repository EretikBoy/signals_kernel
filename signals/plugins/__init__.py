"""Публичный API подсистемы плагинов."""
from .registry import Registry, Entry, make_registry, ALL_REGISTRIES
from .capabilities import Cap, Capable, supports, describe_capabilities
from .discovery import discover, ENTRY_POINT_GROUP

__all__ = [
    "Registry", "Entry", "make_registry", "ALL_REGISTRIES",
    "Cap", "Capable", "supports", "describe_capabilities",
    "discover", "ENTRY_POINT_GROUP",
]
