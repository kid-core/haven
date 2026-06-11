"""P4a — Five-layer system prompt assembler.

Replaces the single flat system prompt with a dynamic assembler
that builds prompts from composable layers.  Each layer is a
callable that returns a string; layers can be registered,
replaced, or removed at runtime.

Usage::

    from core.prompt_assembler import SystemPromptAssembler

    assembler = SystemPromptAssembler(identity_loader=build_system_prompt)
    prompt = assembler.build(session_id="abc", role="default")
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Callable

from core.config import config

logger = logging.getLogger(__name__)

# ── Type aliases ────────────────────────────────────────────────────────────

LayerFn = Callable[["BuildContext"], str]


# ── Build context (data available to every layer) ───────────────────────────

class BuildContext:
    """Immutable snapshot of per-build state passed to every layer.

    Layers read from this context instead of reaching out to globals
    directly, which makes testing trivial: just construct a BuildContext.
    """

    __slots__ = (
        "session_id",
        "role",
        "extra_rules",
        "now",
        "tz",
        "model_name",
        "workspace_root",
    )

    def __init__(
        self,
        session_id: str = "default",
        role: str = "default",
        extra_rules: str = "",
        now: datetime.datetime | None = None,
        tz: str | None = None,
        model_name: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.role = role
        self.extra_rules = extra_rules
        self.now = now or datetime.datetime.now()
        self.tz = tz or os.getenv("TZ", "UTC")
        self.model_name = model_name or config.primary_model
        self.workspace_root = workspace_root or os.getenv("HAVEN_ROOT", "/mnt/z/Haven")


# ── Default layer implementations ───────────────────────────────────────────

def _identity_layer(ctx: BuildContext, identity_text: str) -> str:
    """Static identity loaded at assembler construction time."""
    return identity_text


def _runtime_layer(ctx: BuildContext) -> str:
    """Dynamic runtime context: date, time, session, model, workspace."""
    date_str = ctx.now.strftime("%Y-%m-%d %H:%M")
    return (
        f"[Runtime]\n"
        f"Current time: {date_str} {ctx.tz}\n"
        f"Session: {ctx.session_id}\n"
        f"Model: {ctx.model_name}\n"
        f"Workspace: {ctx.workspace_root}"
    )


def _user_rules_layer(ctx: BuildContext) -> str:
    """User-supplied extra rules injected at build time.

    Returns an empty string when *extra_rules* is empty so the layer
    produces no visual noise in the assembled prompt.
    """
    if not ctx.extra_rules.strip():
        return ""
    return f"[Additional Rules]\n{ctx.extra_rules.strip()}"


def _role_layer(ctx: BuildContext) -> str:
    """Role-specific guidance.

    Each role gets a short behavioural primer.  Unknown roles
    fall through to the default assistant profile.
    """
    roles: dict[str, str] = {
        "default": (
            "You are a helpful assistant.  Respond concisely, use tools when "
            "they clearly help, and ask clarifying questions when uncertain."
        ),
        "coding": (
            "You are a coding assistant.  Prefer reading source files before "
            "suggesting changes.  Run tests after making modifications.  "
            "When proposing large changes, explain the rationale first."
        ),
        "research": (
            "You are a research assistant.  Gather information thoroughly "
            "before forming conclusions.  Cite sources when possible.  "
            "Flag uncertainties explicitly."
        ),
    }
    guidance = roles.get(ctx.role, roles["default"])
    return f"[Role: {ctx.role}]\n{guidance}"


def _tool_layer(ctx: BuildContext) -> str:
    """Tool usage rules — generic guidance.

    Specific tool lists are injected by the Router via *extra_rules*
    (Phase 4b will add per-category tool descriptions).
    """
    return (
        "[Tools]\n"
        "You have access to tools for files, commands, web search, memory, "
        "and communication.  Use the most appropriate tool for each task.  "
        "After receiving tool results, continue the conversation naturally."
    )


# ── Default layer names in build order ──────────────────────────────────────

DEFAULT_LAYERS = ("identity", "runtime", "user_rules", "role", "tool")


# ── Assembler ───────────────────────────────────────────────────────────────

class SystemPromptAssembler:
    """Five-layer system prompt builder.

    Layers are stored as a name → LayerFn mapping.  The build order
    is controlled by ``_order`` (list of layer names).

    Public API: register_layer, remove_layer, set_order, build.
    """

    def __init__(
        self,
        identity_text: str = "",
    ) -> None:
        # Bind identity_text into the identity layer closure
        self._layers: dict[str, LayerFn] = {
            "identity": lambda ctx: _identity_layer(ctx, identity_text),
            "runtime": _runtime_layer,
            "user_rules": _user_rules_layer,
            "role": _role_layer,
            "tool": _tool_layer,
        }
        self._order: list[str] = list(DEFAULT_LAYERS)

    # ── Registration ────────────────────────────────────────────────

    def register_layer(self, name: str, fn: LayerFn, after: str | None = None) -> None:
        """Add or replace a layer.  If *after* is given, insert after that name."""
        self._layers[name] = fn
        if name not in self._order:
            if after and after in self._order:
                idx = self._order.index(after)
                self._order.insert(idx + 1, name)
            else:
                self._order.append(name)

    def remove_layer(self, name: str) -> None:
        """Remove a layer by name (no-op if absent)."""
        self._layers.pop(name, None)
        if name in self._order:
            self._order.remove(name)

    def set_order(self, *names: str) -> None:
        """Explicitly set the layer build order."""
        unknown = set(names) - set(self._layers)
        if unknown:
            raise KeyError(f"Unknown layer(s): {', '.join(sorted(unknown))}")
        self._order = list(names)

    # ── Build ───────────────────────────────────────────────────────

    def build(
        self,
        session_id: str = "default",
        role: str = "default",
        extra_rules: str = "",
        **ctx_kwargs,
    ) -> str:
        """Assemble the full system prompt from all registered layers.

        Parameters are forwarded to :class:`BuildContext`.
        """
        ctx = BuildContext(
            session_id=session_id,
            role=role,
            extra_rules=extra_rules,
            **ctx_kwargs,
        )
        parts: list[str] = []
        for name in self._order:
            fn = self._layers.get(name)
            if fn is None:  # defensive — should not happen after registration
                continue
            layer_text = fn(ctx)
            if layer_text:  # skip empty layers (e.g. no extra_rules)
                parts.append(layer_text)
        return "\n\n".join(parts)

    @property
    def layers(self) -> dict[str, LayerFn]:
        """Read-only view of registered layers."""
        return dict(self._layers)

    @property
    def order(self) -> list[str]:
        """Current build order."""
        return list(self._order)
