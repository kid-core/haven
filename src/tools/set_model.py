"""
Runtime model switching tool — change provider model without restart.

Registers as a SYSTEM-category tool.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool

if TYPE_CHECKING:
    from core.base_provider import BaseProvider

logger = logging.getLogger(__name__)

# Module-level provider list — injected by Router during init
_providers: list[tuple[Any, str | None]] | None = None


def set_providers(providers: list[tuple[Any, str | None]]) -> None:
    """Inject the provider list (called by Router on init)."""
    global _providers  # noqa: PLW0603
    _providers = providers


# ── Provider-scoped model validation ─────────────────────────────────

_PROVIDER_MODELS: dict[int, list[str]] = {
    0: ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"],
    1: [
        "google/gemma-4-31b-it",
        "google/gemma-4-26b-a4b-it",
        "google/gemma-4-9b-it",
        "deepseek/deepseek-chat",
        "openai/gpt-5.5",
    ],
}


def _validate_model(model: str, provider_index: int) -> str | None:
    """Return error message if model isn't valid for *provider_index*, else None."""
    allowed = _PROVIDER_MODELS.get(provider_index)
    if allowed is None:
        return f"Provider index {provider_index} has no allowed-models list."
    if model not in allowed:
        examples = ", ".join(allowed[:4])
        return (
            f"'{model}' is not a valid model for provider[{provider_index}]. "
            f"Must be one of: {examples}"
        )
    return None


@tool(
    name="set_model",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0, rate_limit=5.0),
)
async def set_model(
    model: str,
    provider_index: int = 0,
) -> dict:
    """Switch the LLM model at runtime without restarting Haven.

    IMPORTANT — model-to-provider mapping (follow these rules exactly):
      - Models starting with "deepseek-" (e.g. deepseek-v4-pro) → provider_index=0
      - Models with a slash like "google/gemma-4-31b-it" or
        "openai/gpt-5.5" → provider_index=1

    If the user says "switch to Gemma 4 31B" or "切換到 Gemma 4 31B",
    the model name is "google/gemma-4-31b-it" and since it has a slash
    it MUST use provider_index=1.

    If the user says "switch to DeepSeek v4 Pro", the model is
    "deepseek-v4-pro" with provider_index=0.

    Args:
        model: Exact model identifier e.g. "google/gemma-4-31b-it" or
               "deepseek-v4-pro".
        provider_index: 0 = DeepSeek, 1 = OpenRouter.  Infer from model.

    Returns:
        dict with status, provider info, and previous/current model.
    """
    # ── Auto-infer provider_index from model name pattern ───────
    if "/" in model:
        auto_idx = 1  # has slash → OpenRouter model
    else:
        auto_idx = 0  # no slash → DeepSeek model

    # If user explicitly passed a non-default provider_index, honour it;
    # otherwise use auto-inferred value.
    if provider_index == 0 and auto_idx == 1:
        provider_index = 1
    if _providers is None:
        return {"status": "error", "error": "Provider chain not wired. Restart Haven."}

    if provider_index >= len(_providers):
        return {
            "status": "error",
            "error": f"Provider index {provider_index} out of range. Have {len(_providers)} providers.",
        }

    # ── Validate model against provider scope ────────────────────
    err = _validate_model(model, provider_index)
    if err:
        return {"status": "error", "error": err}

    provider, override = _providers[provider_index]

    try:
        old_model = (
            provider._model if hasattr(provider, "_model")
            else str(provider.get_model())
        )
        provider._model = model
        logger.info(
            "Model switched: provider[%d]=%s  %s → %s",
            provider_index, getattr(provider, "_name", "?"),
            old_model, model,
        )
        return {
            "status": "ok",
            "provider": getattr(provider, "_name", str(type(provider).__name__)),
            "previous_model": old_model,
            "current_model": model,
            "tip": "This change affects only new conversation turns.",
        }
    except Exception as exc:
        logger.exception("Failed to switch model")
        return {"status": "error", "error": str(exc)}
