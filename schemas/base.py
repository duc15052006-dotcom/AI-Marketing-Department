"""Base model and validation layer for schemas.

Provides a robust, zero-dependency BaseModel and Field implementation
with keyword-only initialization, constraint checks, and serialization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field, fields
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, TypeVar

T = TypeVar("T", bound="BaseModel")


class ValidationError(ValueError):
    """Raised when schema validation fails."""
    pass


def field_validator(*field_names: str) -> Callable:
    """Decorator to mark a method as a validator."""
    def decorator(fn: Callable) -> Callable:
        fn.__validator_fields__ = field_names
        return fn
    return decorator


class FieldInfo:
    """Metadata for schema fields."""
    def __init__(
        self,
        default: Any = ...,
        default_factory: Optional[Callable[[], Any]] = None,
        description: str = "",
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        ge: Optional[float] = None,
        le: Optional[float] = None,
        gt: Optional[float] = None,
        lt: Optional[float] = None,
    ) -> None:
        self.default = default
        self.default_factory = default_factory
        self.description = description
        self.min_length = min_length
        self.max_length = max_length
        self.ge = ge
        self.le = le
        self.gt = gt
        self.lt = lt


def Field(
    default: Any = ...,
    *,
    default_factory: Optional[Callable[[], Any]] = None,
    description: str = "",
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    ge: Optional[float] = None,
    le: Optional[float] = None,
    gt: Optional[float] = None,
    lt: Optional[float] = None,
) -> Any:
    """Define a field with validation rules and metadata."""
    info = FieldInfo(
        default=default,
        default_factory=default_factory,
        description=description,
        min_length=min_length,
        max_length=max_length,
        ge=ge,
        le=le,
        gt=gt,
        lt=lt,
    )
    if default_factory is not None:
        return dc_field(default_factory=default_factory, metadata={"field_info": info})
    elif default is not ...:
        return dc_field(default=default, metadata={"field_info": info})
    else:
        return dc_field(metadata={"field_info": info})


class BaseModel:
    """Zero-dependency base model supporting typed fields, constraints, and serialization."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        dataclass(cls, repr=False, kw_only=True)

    def __post_init__(self) -> None:
        cls = self.__class__
        for f in fields(cls):
            name = f.name
            info: Optional[FieldInfo] = f.metadata.get("field_info")
            val = getattr(self, name)

            # Apply constraint validations
            if info:
                if info.min_length is not None and hasattr(val, "__len__") and len(val) < info.min_length:
                    raise ValidationError(
                        f"Field '{name}' length ({len(val)}) is less than minimum {info.min_length}"
                    )
                if info.max_length is not None and hasattr(val, "__len__") and len(val) > info.max_length:
                    raise ValidationError(
                        f"Field '{name}' length ({len(val)}) exceeds maximum {info.max_length}"
                    )
                if info.ge is not None and isinstance(val, (int, float)) and val < info.ge:
                    raise ValidationError(
                        f"Field '{name}' value ({val}) is less than minimum {info.ge}"
                    )
                if info.le is not None and isinstance(val, (int, float)) and val > info.le:
                    raise ValidationError(
                        f"Field '{name}' value ({val}) exceeds maximum {info.le}"
                    )
                if info.gt is not None and isinstance(val, (int, float)) and val <= info.gt:
                    raise ValidationError(
                        f"Field '{name}' value ({val}) must be greater than {info.gt}"
                    )
                if info.lt is not None and isinstance(val, (int, float)) and val >= info.lt:
                    raise ValidationError(
                        f"Field '{name}' value ({val}) must be less than {info.lt}"
                    )

        # Run registered class validators
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if callable(attr) and hasattr(attr, "__validator_fields__"):
                for target_field in attr.__validator_fields__:
                    if hasattr(self, target_field):
                        current_val = getattr(self, target_field)
                        validated_val = attr(cls, current_val)
                        setattr(self, target_field, validated_val)

    def model_dump(self, mode: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        """Serialize model to dictionary."""
        result: Dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            result[f.name] = self._serialize_val(val)
        return result

    def model_copy(self, update: Optional[Dict[str, Any]] = None, deep: bool = False) -> Any:
        """Return a copy of the model with optional field updates."""
        import copy
        cls = self.__class__
        data = self.model_dump()
        if update:
            data.update(update)
        if deep:
            data = copy.deepcopy(data)
        return cls(**data)

    def _serialize_val(self, val: Any) -> Any:
        if isinstance(val, BaseModel):
            return val.model_dump()
        elif isinstance(val, list):
            return [self._serialize_val(item) for item in val]
        elif isinstance(val, dict):
            return {k: self._serialize_val(v) for k, v in val.items()}
        elif isinstance(val, (datetime, date)):
            return val.isoformat()
        elif hasattr(val, "value"):  # Enum
            return val.value
        return val

    def model_dump_json(self) -> str:
        """Serialize model to JSON string."""
        return json.dumps(self.model_dump(), default=str, indent=2)

    def __repr__(self) -> str:
        cls_name = self.__class__.__name__
        attrs = ", ".join(f"{f.name}={getattr(self, f.name)!r}" for f in fields(self))
        return f"{cls_name}({attrs})"
