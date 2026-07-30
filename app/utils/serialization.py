"""Model serialization and deserialization utilities.

Per the Architecture Design Document, every entity flowing between layers
of the application is a Pydantic v2 model (``app.models``). This module
provides small, generic, reusable wrappers around Pydantic v2's own
serialization API (``model_dump``, ``model_dump_json``,
``model_validate``, ``model_validate_json``) so that every call site in
the codebase performs (de)serialization identically — the same JSON mode,
the same error translation into this package's own exception hierarchy —
rather than each call site invoking Pydantic's API slightly differently.

This module contains no knowledge of any specific model defined in
``app.models``; every function here is generic over
``pydantic.BaseModel`` and works identically for any model in that
package (or any future one).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.utils.exceptions import DeserializationError, SerializationError

__all__ = [
    "serialize",
    "serialize_json",
    "serialize_many",
    "deserialize",
    "deserialize_json",
    "deserialize_many",
]

ModelT = TypeVar("ModelT", bound=BaseModel)


def serialize(model: BaseModel) -> dict[str, Any]:
    """Serialize a Pydantic model instance to a plain, JSON-safe dict.

    Uses Pydantic v2's ``mode="json"`` dump, which applies every field's
    configured JSON serializer (for example, the ``UTCDatetime`` type
    alias's ISO-8601/UTC/'Z'-suffix serializer defined in
    ``app.models.base``) — the result is safe to pass directly to
    ``json.dumps`` with no further transformation.

    Args:
        model: The model instance to serialize.

    Returns:
        A dict containing only JSON-safe primitive values.

    Raises:
        SerializationError: If serialization fails for any reason (in
            practice, only possible for a model constructed in a way
            that bypassed its own validation).
    """
    try:
        return model.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - translated into a typed error below
        raise SerializationError(
            f"Failed to serialize an instance of '{type(model).__name__}': {exc}"
        ) from exc


def serialize_json(model: BaseModel) -> str:
    """Serialize a Pydantic model instance directly to a JSON string.

    Args:
        model: The model instance to serialize.

    Returns:
        A JSON-encoded string.

    Raises:
        SerializationError: If serialization fails for any reason.
    """
    try:
        return model.model_dump_json()
    except Exception as exc:  # noqa: BLE001 - translated into a typed error below
        raise SerializationError(
            f"Failed to serialize an instance of '{type(model).__name__}' to JSON: {exc}"
        ) from exc


def serialize_many(models: Iterable[BaseModel]) -> list[dict[str, Any]]:
    """Serialize an iterable of Pydantic model instances to a list of dicts.

    Args:
        models: The model instances to serialize. All are expected to be
            Pydantic model instances, though not necessarily of the same
            concrete type.

    Returns:
        A list of JSON-safe dicts, in the same order as ``models``.

    Raises:
        SerializationError: If any individual model fails to serialize.
    """
    return [serialize(model) for model in models]


def deserialize(model_cls: type[ModelT], data: Any) -> ModelT:
    """Deserialize raw data into a validated instance of ``model_cls``.

    Args:
        model_cls: The target Pydantic model class.
        data: The raw data to validate — typically a dict, but any value
            ``model_cls.model_validate`` accepts is supported.

    Returns:
        A validated instance of ``model_cls``.

    Raises:
        DeserializationError: If ``data`` fails validation against
            ``model_cls``. The underlying Pydantic ``ValidationError``'s
            structured error details are preserved on the raised
            exception's ``details`` attribute.
    """
    try:
        return model_cls.model_validate(data)
    except PydanticValidationError as exc:
        raise DeserializationError(
            model_cls.__name__, "one or more fields failed validation.", details=exc.errors()
        ) from exc


def deserialize_json(model_cls: type[ModelT], json_data: str | bytes) -> ModelT:
    """Deserialize a JSON string or bytes into a validated instance of
    ``model_cls``.

    Args:
        model_cls: The target Pydantic model class.
        json_data: The raw JSON string or bytes to validate.

    Returns:
        A validated instance of ``model_cls``.

    Raises:
        DeserializationError: If ``json_data`` is not valid JSON, or
            parses successfully but fails validation against
            ``model_cls``.
    """
    try:
        return model_cls.model_validate_json(json_data)
    except PydanticValidationError as exc:
        raise DeserializationError(
            model_cls.__name__, "one or more fields failed validation.", details=exc.errors()
        ) from exc


def deserialize_many(model_cls: type[ModelT], items: Iterable[Any]) -> list[ModelT]:
    """Deserialize an iterable of raw data items into a list of validated
    ``model_cls`` instances.

    Args:
        model_cls: The target Pydantic model class.
        items: The raw data items to validate, in order.

    Returns:
        A list of validated instances, in the same order as ``items``.

    Raises:
        DeserializationError: If any individual item fails validation.
            The error identifies which item failed via the exception's
            ``details`` attribute, matching Pydantic's own per-item error
            reporting.
    """
    return [deserialize(model_cls, item) for item in items]
