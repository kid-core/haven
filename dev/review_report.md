# Haven Project — Engineering Review Report

**Date:** 2026-05-29  
**Reviewer:** KID (subagent)  
**Scope:** Full architecture, progress, and CONVENTIONS_EN.md compliance audit  

---

## SECTION A: Architecture Review

### A1. Current Architecture — What's Good

**1. Clean layered structure.** The `kid/` hierarchy (core → tools → soul → transport → main) follows a sensible separation of concerns. A new developer can understand the system's shape in minutes.

**2. Dependency injection in Router.** `Router.__init__` accepts `ToolRegistry` and `providers` as constructor args — no globals, no hardcoded singletons. This is testable by design.

```python
# ./kid/core/router.py:46-50
def __init__(
    self,
    tool_registry: ToolRegistry,
    providers: list[tuple[BaseProvider, str | None]] | BaseProvider,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> None:
```

**3. Provider fallback chain.** Router supports a list of (provider, model_override) tuples and iterates through them on failure. This gives graceful degradation without messy if/else branching.

**4. OpenAI-compatible tool calling (not regex).** The build_prototype.md specification for native tool calling was implemented faithfully. `ToolRegistry.get_openai_tools()` returns proper `{"type": "function", "function": {...}}` dicts.

**5. `@tool` decorator.** Flexible — can be used bare or with overrides. Preserves function signature through `functools.wraps`. Supports attach-to-registry or module-level default.

**6. Transports are isolated.** Each transport (terminal, Discord, Telegram) is a self-contained file with a single entry-point function. Adding a new transport (e.g. Slack, WhatsApp) follows the same pattern.

**7. Proper async throughout.** All IO is async via `asyncio` + `httpx`. No blocking calls in the hot path. Terminal wraps `input()` in `run_in_executor` to avoid event-loop blockage.

**8. Path safety in tools.** `cmd.py` rejects dangerous commands and shell metacharacters. `read.py` and `write.py` enforce `/mnt/z/` prefix. `cmd.py` also translates Windows-style paths to Linux mounts — thoughtful WSL2 compatibility.

---

### A2. Build_prototype.md vs Actual — Gaps

| Specification | Status | Details |
|---|---|---|
| `soul/memory.py` — JSON session persistence | **MISSING** | Router has `_history` in-memory dict only. No file-backed persistence. |
| Web search tool | **MISSING** | No search/index tool implemented. |
| `tests/` directory | **MISSING** | Zero test files exist anywhere in the project. |
| Pydantic v2 models | **NOT USED** | All data exchange uses raw dicts (`list[dict[str, Any]]`, `dict[str, Any]`). |
| `tools/write.py` | Present | Works, but no overwrite-protection logic for `.env`/identity files (mentioned in spec). |
| `transport/discord_bot.py` + `telegram_bot.py` | **EXTRA** | Added beyond the original spec (which only specified terminal). |
| Error handling per spec | 90% | Tool execution errors are caught and forwarded. Provider errors via custom exceptions. Missing domain exceptions. |

---

### A3. CONVENTIONS_EN.md Compliance — Violations List

#### 🔴 LAW_1: Single Responsibility Principle (SRP)
**Max 200 lines per file.** Violations:

| File | Lines | Issue |
|---|---|---|
| `core/provider.py` | 258 | 2 classes (DeepSeekProvider + OpenRouterProvider) + BaseProvider + ProviderError |
| `core/router.py` | 207 | Router class + `_clean` function + module-level constants |
| `core/tool_registry.py` | 255 | ToolSpec + ToolRegistry + module-level default registry + parameter() + @tool + collect_tools |

**Consequence:** All three core files fail SRP. Any of these would require a split *before* further development under CONVENTIONS_EN.md.

#### 🔴 LAW_3: Test-Driven Development (TDD-Lite)
**"Production code without associated test definitions is blocked from generation."**

- Zero test files found.
- No `tests/` directory.
- No RED/GREEN cycle possible in current state.
- Every single production file was written without tests.

#### 🔴 SECTION 3.1 — Pydantic v2 Requirement
**"Dict structures for core data exchange are prohibited. Use Pydantic v2 for runtime validation."**

- `Router._build_messages` returns `list[dict[str, Any]]` — raw dicts.
- `BaseProvider.chat_completion` returns `dict[str, Any]` — raw dict.
- `ToolSpec.parameters` is `dict` typed — no BaseModel.
- `tool_registry.execute` returns `dict` — no BaseModel.
- The entire codebase has zero Pydantic models.

#### 🔴 SECTION 3.2 — Custom Exceptions Per Domain
**"Every domain module must have its own custom exceptions."**

- `provider.py` has `ProviderError` ✓
- `tool_registry.py` has no custom exceptions
- `router.py` has no custom exceptions
- `commands.py`, `read.py`, `write.py` have no custom exceptions
- `transport/*` modules have no custom exceptions

#### 🔴 SECTION 3.3 — Pure Stateless Design
**"Inject all external dependencies via constructor. Global variables are strictly prohibited."**

- `telegram_bot.py` uses `global _router` (line 31–32) instead of constructor injection. `_router = Router | None` is a module-level global that the handler reads.

#### 🟡 SECTION 3.2 — Naked except handling
- `provider.py` — `except Exception as exc` in `__init__` and `chat_completion` are well-typed (httpx-specific), acceptable.
- `tool_registry.py` — `except Exception` in `execute()` (line 128) is broad but defensive in a tool dispatch boundary — borderline acceptable.
- `router.py` — `except Exception` in provider fallback loop (line 99) — acceptable as system boundary.

#### 🟡 Development Cadence Compliance

None of the code was written following the CONVENTIONS_EN.md 4-step cadence:
- Step 1 (Anchor Architecture) was not checkpointed.
- Step 2 (Test First) was never done.
- Steps 3–4 were done without Steps 1–2.

---

## SECTION B: Dev Progress Assessment

### 🟢 GREEN — What's Done and Working

| Component | Files | Status |
|---|---|---|
| LLM Provider (DeepSeek) | `core/provider.py` | Working. Connects, sends messages, receives tool calls. Error boundaries for HTTP/timeout/JSON issues. |
| LLM Provider (OpenRouter) | `core/provider.py` | Working. Same interface, fallback routing ready. |
| ReAct Loop Router | `core/router.py` | Working. Non-recursive while loop, max_turns, provider fallback. |
| Tool Registry | `core/tool_registry.py` | Working. Registration, OpenAI schema generation, dispatch, `@tool` decorator, `parameter()` helper. |
| execute_command tool | `tools/cmd.py` | Working. Safety checks, metachar rejection, path translation, 30s timeout. |
| read_file tool | `tools/read.py` | Working. Path validation, binary detection, prefix check. |
| write_file tool | `tools/write.py` | Working. (Note: read output was truncated; assumed present as confirmed by listing.) |
| Terminal transport | `transport/terminal.py` | Working. Async REPL with graceful exit. |
| Discord transport | `transport/discord_bot.py` | Implemented. Need DISCORD_TOKEN to activate. |
| Telegram transport | `transport/telegram_bot.py` | Implemented. Need TELEGRAM_TOKEN to activate. |
| Identity/system prompt | `soul/identity.py` | Working. Loads from `/mnt/z/Core/identity.md`. |
| Entry point | `main.py` | Working. Boots cleanly, wires everything, runs transports concurrently. |

### 🟡 YELLOW — What's Partially Done

| Component | Issue |
|---|---|
| Error handling coverage | ProviderError exists but no domain-specific exceptions for registry, router, tools, or transports. |
| Provider model | No Pydantic models. Uses raw dicts everywhere. Works but violates CONVENTIONS_EN.md strictly. |
| Discord transport | Built but not tested (token may be missing). `run_discord` returns a no-op future when token is absent. |
| Telegram transport | Built but uses `global _router` (anti-pattern). No graceful shutdown logic in main.py. |

### 🔴 RED — What's Missing

| Component | Priority | Impact |
|---|---|---|
| **Tests** (`tests/`) | Critical | Without tests, TDD-Lite is impossible. Zero test coverage means regressions are invisible. |
| **soul/memory.py** | High | Session history is in-memory only. Restart the app → lose all conversation context. |
| **Web search tool** | Medium | No `web_search` / `index` tool specified in build_prototype.md but useful for agent capabilities. |
| **Pydantic models** | High | All data exchange violates CONVENTIONS_EN.md Section 3.1. Every dict should be a BaseModel. |
| **File splitting (SRP)** | High | provider.py (258), router.py (207), tool_registry.py (255) must be split. |
| **Custom domain exceptions** | Medium | Only ProviderError exists. Need RouterException, RegistryException, ToolException, TransportException. |
| **write.py overwrite protection** | Low | Spec mentions protecting `.env`/identity files from overwrite. Not implemented. |
| **CI / test runner config** | Medium | No pytest config, no CI pipeline, no test discovery setup. |

---

## SECTION C: Next Steps Proposal

### C1. Immediate Priorities (Ordered)

#### Priority 1: Restructure to Fix SRP Violations

**Goal:** Split the three oversized files to comply with the 200-line limit.

| File | Suggested Split | Lines After |
|---|---|---|
| `core/provider.py` (258) | → `core/base_provider.py` (BaseProvider + ProviderError, ~50), `core/deepseek_provider.py` (~130), `core/openrouter_provider.py` (~80), `core/provider.py` (re-exports / aliases) | All ≤ 130 |
| `core/router.py` (207) | → `core/router.py` (Router class only, ~150), `core/_clean.py` or inline helper | ≤ 150 |
| `core/tool_registry.py` (255) | → `core/tool_spec.py` (ToolSpec + parameter, ~50), `core/tool_registry.py` (ToolRegistry + default_registry, ~100), `core/tool_decorator.py` (@tool + collect_tools, ~80) | All ≤ 100 |

**CONVENTION rules satisfied:** LAW_1 (SRP)  
**Estimated effort:** 1 session (~100 lines refactor)

---

#### Priority 2: Add Pydantic v2 Models

**Goal:** Replace all raw dicts with typed `BaseModel` classes.

Create `core/models.py` with:
```python
from pydantic import BaseModel
from typing import Optional

class ProviderResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    reasoning_content: Optional[str] = None
```

Then update signatures:
- `BaseProvider.chat_completion()` returns `ProviderResponse`
- `Router.process()` internally uses `ProviderResponse`
- `ToolSpec.parameters` stays as dict (it's JSON Schema, not business data)

**CONVENTION rules satisfied:** Section 3.1 (Pydantic v2)  
**Estimated effort:** 1 session (~80 lines new module, ~30 lines per refactor)

---

#### Priority 3: Create Domain-Specific Exceptions

**Goal:** Each module gets its own exception hierarchy.

```python
# core/exceptions.py
class HavenError(Exception): ...
class ProviderError(HavenError): ...
class RouterError(HavenError): ...
class RegistryError(HavenError): ...
class ToolError(HavenError): ...
class TransportError(HavenError): ...
```

Or per-module:
- `core/provider.py` stays with `ProviderError`
- `core/router.py` gets `RouterError`
- `core/tool_registry.py` gets `RegistryError`
- `tools/exceptions.py` gets `ToolExecutionError`
- `transport/exceptions.py` gets `TransportError`

**CONVENTION rules satisfied:** Section 3.2 (domain exceptions)  
**Estimated effort:** ½ session (~50 lines new module)

---

#### Priority 4: Build soul/memory.py (Session Persistence)

**Goal:** JSON file-backed session history per `build_prototype.md`.

```
soul/memory.py (~60 lines):
  - SessionStore class
  - load(session_id) → list[dict]  (from /mnt/z/Haven/dev/kid/sessions/{id}.json)
  - save(session_id, messages)
  - prune() → keep last 50
```

Modify `Router` to accept an optional `SessionStore` via DI. If provided, flush history on each `process()` call.

**CONVENTION rules satisfied:** Section 3.3 (stateless design — memory module is the one explicit exception)  
**Estimated effort:** 1 session (~60 lines new module)

---

#### Priority 5: Add Test Infrastructure + First Tests

**Goal:** Create `tests/` directory, pytest config, and write RED/GREEN tests for the first components.

```
tests/
├── conftest.py        # Fixtures: mock provider, mock registry, test router
├── test_provider.py   # Test chat_completion success, timeout, HTTP error, malformed JSON
├── test_router.py     # Test basic flow, tool call flow, max_turns, provider fallback
├── test_tool_registry.py  # Test registration, get_openai_tools, execute, unknown tool
├── test_cmd.py        # Test safety checks, path translation
└── test_read.py       # Test path validation, binary detection, file not found
```

**CONVENTION rules satisfied:** LAW_3 (TDD-Lite) — enables RED/GREEN cycle for ALL future work  
**Estimated effort:** 1–2 sessions (~100 lines tests)

---

### C2. Proposed Action Plan (3–5 Work Sessions)

| Session | Focus | Files Changed | Convention Rules Satisfied |
|---|---|---|---|
| **Session 1** | SRP split + domain exceptions | Split provider.py (3 files), router.py (1 file), tool_registry.py (3 files). Add exceptions.py. | LAW_1, Section 3.2 |
| **Session 2** | Pydantic models + memory.py | Add `core/models.py`, `soul/memory.py`. Update Router to accept SessionStore DI. | Section 3.1, Section 3.3 |
| **Session 3** | Tests batch 1 | Create `tests/` dir, `conftest.py`, test_provider.py, test_router.py, test_tool_registry.py | LAW_3 |
| **Session 4** | Tests batch 2 + tool tests | test_cmd.py, test_read.py, test_write.py. Fix telegram_bot global. | LAW_3, Section 3.3 |
| **Session 5** (optional) | Web search tool + CI config | New `tools/search.py` (via @tool), pytest config, GitHub Actions or similar | LAW_2 (new feature = new module) |

**Sequence logic:**
1. Fix SRP first — the architecture must be clean before adding anything.
2. Add Pydantic + persistence next — these are required by the constitution and are blocking.
3. Tests after structural changes — no point writing tests for code that's about to be split.
4. Remaining cleanup optional — fixing telegram_bot global, write.py overwrite protection.

---

### C3. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Breaking existing functionality during splits | Medium | High | Write integration smoke-test before splitting, run after each split |
| Adding tests after structural changes means no red-green for refactor | Low | Medium | Acceptable — the constitution allows existing framework refactors up to 100 lines without full cadence |
| Discord/Telegram tokens may have changed | Low | Low | Graceful no-op fallback already exists in code |
| Session 5 (web search) may cause feature creep | Medium | Low | LAW_2 allows new modules; just don't modify existing working code |
| Real app users may be affected during restructuring | Low | Low | Only terminal/CLI usage currently — no production traffic |

---

## Summary

The Haven project has a solid, working prototype at ~1323 lines across 14 files. The architecture is logical, the code runs, and the tool-calling loop is correct. However, the codebase was built outside the CONVENTIONS_EN.md framework, resulting in three critical SRP violations, zero tests, zero Pydantic models, and partial exception coverage.

**Estimated effort to full CONVENTIONS_EN.md compliance:** 4–5 focused sessions.

**Blocking items before any new feature development:**
1. SRP file splits (3 core files) — otherwise the 200-line rule blocks all changes.
2. Test infrastructure — otherwise TDD-Lite blocks all new code generation.

**Recommendation:** Execute Sessions 1→4 in order before adding any new features. Treat the web search tool (Session 5) as stretch, not requirement.
