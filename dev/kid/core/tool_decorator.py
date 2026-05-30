"""@tool decorator + default registry singleton (Phase 0 extended)."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

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

    Bare (``@tool``) or parameterised (``@tool(name="...", category=..., policy=...)``).
    Attaches the ToolSpec as ``__tool_spec__`` on the wrapper.

    Phase 0 additions:
        category:  ToolCategory enum for classification.
        policy:    ToolPolicy for gates (confirm, rate_limit, timeout).
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(
                f"@tool can only decorate async functions. "
                f"{fn.__qualname__} is not async."
            )

        _name = name or fn.__name__
        _desc = description or (fn.__doc__ or "").strip().split("\n")[0]
        _params: dict = (
            parameters
            if parameters is not None
            else {"type": "object", "properties": {}, "required": []}
        )
        _category = category or ToolCategory.SYSTEM
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
