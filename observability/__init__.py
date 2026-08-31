"""Platform observability exports."""

from observability.inspector import (
    InspectorError,
    InspectorNotFoundError,
    InspectorScopeError,
    InspectorUnavailableError,
    PlatformInspector,
)

__all__ = [
    "InspectorError",
    "InspectorNotFoundError",
    "InspectorScopeError",
    "InspectorUnavailableError",
    "PlatformInspector",
]
