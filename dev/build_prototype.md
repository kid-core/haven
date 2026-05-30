# Haven Core Prototype — Build Specification

## Overview

Build a Python prototype for "Haven" — a lightweight, reliable AI assistant core that uses **native OpenAI-compatible tool calling** (not regex text parsing). This will serve as a fallback/escape system when the main OpenClaw agent is unavailable.

Directory: `/mnt/z/Haven/dev/kid/`

All development is governed by `CONVENTIONS_EN.md` (Three Iron Laws, TDD-Lite, Section 3.5 craftsmanship).

Must be runnable with `./start.sh` after setup.

---

## Current Architecture

```
kid/
├── core/
│   ├── __init__.py
│   ├── base_provider.py    # Abstract BaseProvider + ProviderError
│   ├── http_provider.py    # Config-driven HttpProvider (one class, any API)
│   ├── categories.py       # Phase 0: ToolCategory enum + default_policy()
│   ├── policy.py           # Phase 0: ToolPolicy/ToolProfile/RateLimitTracker
│   ├── category_router.py  # Phase 1b: CategoryRule/ExecutionMode routing
│   ├── router.py           # State machine pipeline (non-recursive ReAct loop w/ Phase 0-4)
│   ├── tool_spec.py        # ToolSpec dataclass (with category + policy)
│   ├── tool_registry.py    # ToolRegistry with dict dispatch + policy enforce
│   ├── tool_decorator.py   # @tool decorator + default registry (with category + policy)
│   ├── models.py           # Pydantic v2 data models
│   └── exceptions.py       # Domain exception hierarchy
├── tools/
│   ├── __init__.py         # Register all built-in tools
│   ├── cmd.py              # Phase 0: Safe shell execution (SYSTEM, require_confirm)
│   ├── write.py            # Phase 0: File write (FILES, require_confirm)
│   ├── read.py             # Phase 0: File read (FILES)
│   ├── search.py           # Phase 0: Tavily web search (WEB)
│   ├── memory_search.py    # Phase 2a: Long-term memory CRUD + search
│   ├── spawn_tool.py       # Phase 4: Sub-task delegation tool
│   ├── spawn_child.py      # Phase 4: SpawnManager
│   ├── ollama_provider.py  # Phase 2b: Ollama embedding + minicpm-v provider
│   ├── categories.py       # Re-export shim → core.categories
│   ├── policy.py           # Re-export shim → core.policy
│   └── mcp/                # Phase 1a: MCP integration
│       ├── __init__.py
│       ├── client.py       # MCPStdioClient + MCPSseClient
│       ├── discovery.py    # Dynamic MCP tool discovery
│       └── registry.py     # MCPBridge → ToolRegistry bridge
├── soul/
│   ├── __init__.py
│   ├── identity.py         # System prompt assembly + LTM context
│   └── memory/             # Phase 2a: Persistent memory subsystem
│       ├── __init__.py
│       ├── session_store.py    # SessionStore (migrated from old soul/memory.py)
│       ├── long_term.py        # LongTermMemory — JSON-persistent CRUD
│       ├── summarizer.py       # Rule-based conversation summary compression
│       ├── index.py            # MemoryIndex — full-text keyword search
│       └── vector_index.py     # Phase 2b: VectorIndex — ollama cosine similarity
├── learning/               # Phase 3: Self-improvement subsystem
│   ├── __init__.py
│   ├── skill_store.py      # SkillStore — draft→active→deprecated lifecycle
│   ├── skill_factory.py    # SkillFactory — pattern detection + draft generation
│   └── skill_refiner.py    # SkillRefiner — usage tracking + auto-adjustment
├── transport/
│   ├── __init__.py
│   ├── terminal.py         # Simple terminal REPL
│   ├── discord_bot.py      # Discord @mention and DM handling
│   └── telegram_bot.py     # Telegram message handling
├── tests/
│   ├── conftest.py
│   ├── test_smoke.py
│   ├── test_phase0_policy.py
│   ├── test_phase1_mcp.py
│   ├── test_phase1b_2a.py
│   ├── test_phase3_learning.py
│   └── test_phase4_spawn.py
├── start.sh                # One-click launcher
├── main.py                 # Entry point with graceful shutdown (all phases wired)
└── ruff.toml               # Ruff linter config
```

---

## Component Specifications

### 1. `core/base_provider.py` — Abstract LLM Provider Interface

```python
from abc import ABC, abstractmethod
from typing import Any

class ProviderError(Exception): ...

class BaseProvider(ABC):
    @abstractmethod
    async def chat_completion(self, messages, tools=None,
                              temperature=None, max_tokens=None) -> dict[str, Any]: ...

    @abstractmethod
    def get_model(self, override=None) -> str: ...

    @abstractmethod
    async def close(self) -> None: ...
```

### 2. `core/http_provider.py` — Config-Driven HTTP Provider

Single class for any OpenAI-compatible API. Accepts all differences as constructor config:

```python
class HttpProvider(BaseProvider):
    def __init__(self, *, name: str, model: str, base_url: str,
                 api_key_env: str, timeout: float = 120.0,
                 default_temperature: float = 0.3,
                 headers_extra: dict[str, str] | None = None): ...

    async def chat_completion(self, messages, tools=None,
                              temperature=None, max_tokens=None) -> ProviderResponse:
        # Uses guard clauses: early raise on HTTP/timeout/parse errors
        # Returns ProviderResponse (Pydantic model)
```

Usage:

```python
deepseek = HttpProvider(
    name="DeepSeek",
    model="deepseek-v4-flash",
    base_url="https://api.deepseek.com/v1/chat/completions",
    api_key_env="DEEPSEEK_API_KEY",
)
openrouter = HttpProvider(
    name="OpenRouter",
    model="google/gemma-4-26b-a4b-it",
    base_url="https://openrouter.ai/api/v1/chat/completions",
    api_key_env="OPENROUTER_API_KEY",
    default_temperature=0.7,
    headers_extra={"HTTP-Referer": "...", "X-Title": "Haven"},
)
```

### 3. `core/tool_spec.py` + `core/tool_registry.py` + `core/tool_decorator.py`

Three-file SRP-compliant split of the old monolithic tool_registry:

**`tool_spec.py`** — ToolSpec dataclass:
```python
@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[Any]]
```

**`tool_registry.py`** — ToolRegistry (dict dispatch pattern):
```python
class ToolRegistry:
    def __init__(self): ...
    def add(self, spec: ToolSpec) -> ToolSpec: ...
    def get_openai_tools(self) -> list[dict]: ...
    async def execute(self, tool_call_id: str, name: str, arguments: dict) -> dict: ...
    def __contains__(self, name: str) -> bool: ...
    def __len__(self) -> int: ...
    def __iter__(self): ...
```

**`tool_decorator.py`** — @tool decorator + default registry:
```python
def tool(_func=None, *, name=None, description=None,
         parameters=None, registry=None) -> Any: ...
def get_default_registry() -> ToolRegistry: ...
```

### 4. `core/router.py` — State Machine Router

Non-recursive ReAct loop with provider fallback chain.

```python
class Router:
    def __init__(self, tool_registry: ToolRegistry,
                 providers: list[tuple[BaseProvider, str | None]],
                 system_prompt: str = DEFAULT_SYSTEM_PROMPT): ...

    async def process(self, user_message: str,
                      session_id: str = "default",
                      max_turns: int = 10) -> str: ...
```

Key rules:
- **No recursion.** Use a `while` loop with a `max_turns` limit.
- **Proper roles:** user → assistant (with tool_calls) → tool → assistant (with tool_calls) → ...
- **Tool results are `{"role": "tool", "tool_call_id": "...", "content": "..."}`**
- **Provider fallback:** If the primary provider fails, try the next in the chain.
- **Error handling:** If a tool call fails, return error message as tool content (don't crash).
- **Depth limit returns a clear error message, not a mode switch.**

### 5. `core/models.py` — Pydantic v2 Data Models

```python
class ProviderResponse(BaseModel):
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    reasoning_content: str | None = None

class ToolResult(BaseModel):
    role: str = "tool"
    tool_call_id: str
    content: str
```

### 6. `core/exceptions.py` — Domain Exceptions

```python
class HavenError(Exception): ...
class ProviderError(HavenError): ...
class RouterError(HavenError): ...
class RegistryError(HavenError): ...
```

### 7. Tools

Each tool is a self-contained Python file registered via `@tool`:

- **`tools/cmd.py`** — `execute_command(cmd: str)` — Safe shell execution with metacharacter rejection, dangerous command blocklist, 30s timeout.
- **`tools/write.py`** — `write_file(path: str, content: str)` — Writes files under `/mnt/z/`, rejects overwrites of protected files (`.env`, `.key`).
- **`tools/read.py`** — `read_file(path: str)` — Reads files under `/mnt/z/`, auto-detects binary files.

### 8. `soul/identity.py` — System Prompt Builder

Loads `/mnt/z/Core/identity.md` for base identity. Builds system prompt with identity + tool usage instructions + mode context.

### 9. `soul/memory.py` — Session History

```python
class SessionStore:
    def __init__(self, session_dir, max_messages=50): ...
    def load(self, session_id) -> list[dict]: ...
    def save(self, session_id, messages) -> None: ...
```

- Per-session JSON files at `/mnt/z/Haven/dev/kid/sessions/{session_id}.json`
- Keeps last 50 messages, prunes on save

### 10. Transports

Three concurrent transports, all share the same Router instance via DI:

- **`transport/terminal.py`** — Simple REPL with `Cris>` prompt. Runs in thread executor to avoid blocking the event loop.
- **`transport/discord_bot.py`** — Responds to @mentions and DMs. Requires `DISCORD_TOKEN`.
- **`transport/telegram_bot.py`** — Handles text messages. Uses DI (no globals). Requires `TELEGRAM_TOKEN`.

### 11. `main.py` — Entry Point

```python
async def main():
    # 1. Signal handlers registered (SIGINT/SIGTERM → asyncio.Event)
    # 2. Init ToolRegistry
    # 3. Register built-in tools (import tools/__init__.py)
    # 4. Init providers (DeepSeek primary, OpenRouter fallback)
    # 5. Init Router
    # 6. Start all transports concurrently
    # 7. Wait for shutdown signal or any transport exit
    # 8. Graceful shutdown: stop Telegram → cancel tasks → close providers
```

### 12. `start.sh` — One-Click Launcher

```bash
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
source /mnt/z/Core/.venv/bin/activate
echo "🏝️  Starting Haven..."
echo "     Ctrl+C to stop gracefully"
python main.py
```

---

## Implementation Notes

- **Use `asyncio` everywhere.** All IO should be async.
- **Use `httpx`** for async HTTP calls to LLM API.
- **Dependency injection** — Router receives ToolRegistry and Provider as constructor args, not hardcoded.
- **Pydantic v2** for all core data exchange. No raw dicts across module boundaries.
- **Guard clauses** — Errors caught early and raised immediately. No nested error handling.
- **No globals** — Telegram handler stores router as instance attribute, not module-level `global`.
- **Security** — Reject path traversal, dangerous shell commands, writes to protected files.
- **Graceful shutdown** — Signal handlers, ordered cleanup (Telegram → tasks → providers).

---

## How to Test

```bash
# Activate environment
source /mnt/z/Core/.venv/bin/activate

# Option A: One-click launcher
cd /mnt/z/Haven/dev && ./kid/start.sh

# Option B: Manual
cd /mnt/z/Haven/dev && python kid/main.py

# Full test suite (143 tests)
cd /mnt/z/Haven/dev && python -m pytest kid/tests/ -v

# Per-phase tests
python -m pytest kid/tests/test_phase0_policy.py -v     # Policy layer
python -m pytest kid/tests/test_phase1_mcp.py -v         # MCP integration
python -m pytest kid/tests/test_phase1b_2a.py -v         # Routing + Memory
python -m pytest kid/tests/test_phase3_learning.py -v    # Self-learning
python -m pytest kid/tests/test_phase4_spawn.py -v       # Sub-task delegation

# Lint
ruff check dev/kid/
pylint dev/kid/
```

Expected behaviour:
1. Type a message
2. System calls LLM, executes tools, returns response
3. Type "exit" or Ctrl+C to shut down gracefully

---

## Environment

- API keys loaded from `/mnt/z/Core/.env` and `/root/.openclaw/env`
- DeepSeek: `DEEPSEEK_API_KEY`
- OpenRouter (fallback): `OPENROUTER_API_KEY`
- Discord: `DISCORD_TOKEN`
- Telegram: `TELEGRAM_TOKEN`
- Virtual env: `/mnt/z/Core/.venv/` (activate before running)

---

## Governing Documents

- `CONVENTIONS_EN.md` — Architectural constitution (Three Iron Laws, TDD-Lite, Section 3.5 craftsmanship)
- `CONVENTIONS.md` — Same, in Chinese

All code must comply. Violation triggers a warning from AI_Engineer_KID.
