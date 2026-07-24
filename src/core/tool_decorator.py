"""@tool decorator + default registry singleton (Phase 0 extended).

Automatically generates OpenAI-compatible JSON Schema ``parameters``
from the decorated function's Python type hints.
"""

from __future__ import annotations

import functools
import inspect
import typing
import types
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, get_origin, get_args

from .categories import ToolCategory
from .policy import ToolPolicy
from .tool_spec import ToolSpec

if TYPE_CHECKING:
    from .tool_registry import ToolRegistry

# ---------------------------------------------------------------------------
# Module-level default registry  (lazy init)
# ---------------------------------------------------------------------------

_default_registry: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    """Return the module-level default ToolRegistry, creating it lazily."""
    global _default_registry  # noqa: PLW0603
    if _default_registry is None:
        from .tool_registry import ToolRegistry

        _default_registry = ToolRegistry()
    return _default_registry


# ---------------------------------------------------------------------------
# Parameter schema generation
# ---------------------------------------------------------------------------

# Mapping from Python type to JSON Schema type
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
    type(None): "null",
}


def _py_type_to_json(tp: type) -> str:
    """Map a Python type annotation to a JSON Schema type string."""
    origin = get_origin(tp)

    # Handle UnionType (X | Y syntax, e.g. dict | None)
    if origin in (typing.Union, types.UnionType):
        args = get_args(tp)
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _py_type_to_json(non_none[0])
        return "null"

    # Handle generic types: list[str], dict[str, int]
    if origin is not None:
        if origin in (list, typing.List):
            return "array"
        if origin in (dict, typing.Dict):
            return "object"
        return "string"

    return _TYPE_MAP.get(tp, "string")


def _build_parameters(fn: Callable[..., Any]) -> dict:
    """Build a JSON Schema ``parameters`` dict from *fn*'s signature.

    Excludes ``self`` / ``cls`` (bound methods).
    """
    sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        # Skip self/cls
        if name in ("self", "cls"):
            continue

        # Determine JSON Schema type
        json_type = "string"
        param_desc = ""
        if param.annotation is not inspect.Parameter.empty:
            json_type = _py_type_to_json(param.annotation)

        # Check for default → optional
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            # Include default value in description for hint
            default_val = param.default
            if default_val is not None:
                param_desc = f"(default: {default_val})"

        prop: dict[str, Any] = {"type": json_type}
        if param_desc:
            prop["description"] = param_desc
        properties[name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------

def tool(
    _func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    parameters: dict | None = None,
    category: ToolCategory | None = None,
    policy: ToolPolicy | None = None,
    registry: ToolRegistry | None = None,
) -> Any:
    """Mark an async function as a tool and register it.

    When ``parameters`` is omitted, the decorator automatically builds a
    JSON Schema from the function's type hints  (str → string, int →
    integer, Optional → optional, etc.).  Explicit ``parameters`` always
    takes precedence.

    Bare (``@tool``) or parameterised (``@tool(name="...", category=..., policy=...)``).
    Attaches the ToolSpec as ``__tool_spec__`` on the wrapper.
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(
                f"@tool can only decorate async functions. "
                f"{fn.__qualname__} is not async."
            )

        _name = name or fn.__name__
        _desc = description or (fn.__doc__ or "").strip().split("\n")[0]

        # Auto-generate parameters from function signature when not given
        _params: dict = parameters if parameters is not None else _build_parameters(fn)

        _category = category or ToolCategory.ENV
        _policy = policy or ToolPolicy()

        spec = ToolSpec(
            name=_name,
            description=_desc,
            parameters=_params,
            handler=fn,
            category=_category,
            policy=_policy,
        )
        reg = registry or get_default_registry()
        reg.add(spec)

        @functools.wraps(fn)
        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            return await fn(*args, **kwargs)

        _wrapper.__tool_spec__ = spec  # type: ignore[attr-defined]
        return _wrapper

    if _func is not None:
        return _decorator(_func)
    return _decorator
