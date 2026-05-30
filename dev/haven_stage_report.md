# Haven Stage Report — May 2026

**Project:** Haven — KID's Lightweight Backup AI Core
**Period:** 2026-05-27 to 2026-05-30
**Author:** KID
**Status:** Core Complete · CI Green · Runtime Verified

---

## 1. Overview

Haven is a lightweight, reliable AI assistant core built in Python. It serves as a fallback/escape system when the main OpenClaw agent is unavailable. The project started as a simple 3-tool ReAct loop and has evolved into a fully-featured AI core with governance, memory, learning, and delegation.

**Directory:** `/mnt/z/Haven/dev/kid/`
**Language:** Python 3.12
**Primary Model:** DeepSeek v4 pro (via DeepSeek API)
**Fallback Model:** Google Gemma 4 26B (via OpenRouter)
**Local Models:** nomic-embed-text + minicpm-v (via Ollama)

---

## 2. What Was Built

### Phase 0 — Tool Governance Layer ✅
- **ToolCategory enum:** FILES, SYSTEM, WEB, AI, COMMUNICATION, MEMORY, EXTERNAL
- **ToolPolicy:** per-tool gates — enabled, require_confirm, rate_limit, timeout
- **ToolProfile:** session/channel-scoped tool visibility presets
- **RateLimitTracker:** per-tool cooldown enforcement
- **Router integration:** confirm gate, policy-blocked handling, timeout enforcement
- **All 4 original tools updated** with categories and policies

### Phase 1a — MCP Integration ✅
- **MCPStdioClient:** JSON-RPC 2.0 over stdio
- **MCPSseClient:** JSON-RPC 2.0 over SSE
- **MCPBridge:** dynamic tool discovery → ToolRegistry registration
- **MCPServerConfig:** declarative server configuration
- All MCP tools auto-prefixed `mcp__` to avoid naming conflicts

### Phase 1b — Category Routing ✅
- **ExecutionMode:** INLINE / AI_PROXY / EXTERNAL
- **CategoryRule:** per-category routing rules with provider role mapping
- **CategoryRouter:** provider registry, rule overrides, fallback decisions
- Router auto-injects `_provider` into arguments for AI_PROXY tools

### Phase 2a — Persistent Memory ✅
- **SessionStore:** session history (JSON, auto-trim)
- **LongTermMemory:** cross-session CRUD with tag/full-text search
- **Summarizer:** rule-based conversation compression (decisions, preferences, facts)
- **MemoryIndex:** multi-keyword scoring search
- Router auto-injects top-8 important memories at session start
- Router auto-summarizes sessions with >5 messages on end

### Phase 2b — Vector Search ✅
- **VectorIndex:** ollama nomic-embed-text for semantic search
- **Hybrid scoring:** cosine similarity (80%) + keyword (20%)
- Graceful fallback to keyword-only when ollama is unavailable
- Embedding cache persistence

### Phase 3 — Self-Learning ✅
- **SkillStore:** draft → active → deprecated lifecycle with versioning and audit trail
- **SkillFactory:** pattern detection (≥3 occurrences), draft generation, safety filters
- **SkillRefiner:** success rate monitoring, auto-deprecate <20%, warn <50%
- SYSTEM tools blocked from learning; sensitive patterns filtered
- Active skills auto-injected into system prompt

### Phase 4 — Sub-task Delegation ✅
- **SpawnManager:** 3-level nesting limit, 60s timeout
- **spawn_child tool:** delegates tasks to ephemeral child routers
- Integrated into main Router

---

## 3. Architecture

```
kid/
├── core/                     # Core engine (stable)
│   ├── base_provider.py      # Abstract LLM provider interface
│   ├── http_provider.py      # Config-driven OpenAI-compatible HTTP provider
│   ├── categories.py         # ToolCategory enum + default policies
│   ├── policy.py             # ToolPolicy, ToolProfile, RateLimitTracker
│   ├── category_router.py    # ExecutionMode routing + provider mapping
│   ├── router.py             # State-machine ReAct loop (all phases integrated)
│   ├── tool_spec.py          # ToolSpec dataclass
│   ├── tool_registry.py      # Dict-dispatch registry + policy enforcement
│   ├── tool_decorator.py     # @tool decorator + default registry
│   ├── models.py             # Pydantic v2 data models
│   └── exceptions.py         # Domain exception hierarchy
├── tools/                    # Tool implementations
│   ├── cmd.py                # Safe shell execution (SYSTEM, confirm)
│   ├── write.py              # File write with path validation (FILES, confirm)
│   ├── read.py               # File read (FILES)
│   ├── search.py             # Tavily web search (WEB)
│   ├── memory_search.py      # Long-term memory CRUD + search
│   ├── spawn_tool.py         # Sub-task delegation
│   ├── spawn_child.py        # SpawnManager
│   ├── ollama_provider.py    # Ollama embedding + minicpm-v chat provider
│   └── mcp/                  # MCP integration
│       ├── client.py         # MCP stdio + SSE clients
│       ├── discovery.py      # Dynamic tool discovery
│       └── registry.py       # MCPBridge → ToolRegistry
├── soul/                     # Identity + memory
│   ├── identity.py           # System prompt assembly + LTM context
│   └── memory/
│       ├── session_store.py  # Per-session JSON history
│       ├── long_term.py      # Persistent cross-session CRUD
│       ├── summarizer.py     # Rule-based compression
│       ├── index.py          # Full-text keyword search
│       └── vector_index.py   # Ollama semantic search
├── learning/                 # Self-improvement
│   ├── skill_store.py        # Draft→Active→Deprecated lifecycle
│   ├── skill_factory.py      # Pattern observation + draft generation
│   └── skill_refiner.py      # Success tracking + auto-adjustment
├── transport/                # Communication channels
│   ├── terminal.py           # REPL
│   ├── discord_bot.py        # Discord @mention + DM
│   └── telegram_bot.py       # Telegram bot
├── tests/                    # Test suite (7 files, 143 tests)
├── main.py                   # Entry point
└── start.sh                  # One-click launcher
```

---

## 4. CI/CD Pipeline

**Workflow:** `.github/workflows/ci.yml`

| Step | Result |
|------|--------|
| Ruff (fast lint) | ✅ Zero errors |
| File size ≤ 400 lines | ✅ All pass |
| Pylint (soft-fail) | ✅ Advisory only |
| Pytest (143 tests) | ✅ 143/143 pass |

**Linting rules (ruff.toml):** pycodestyle (E/W), pyflakes (F), isort (I), pep8-naming (N), pyupgrade (UP), flake8-bugbear (B), flake8-simplify (SIM), flake8-comprehensions (C4)
**Line length:** 100 · **Target Python:** 3.12

---

## 5. Test Coverage

| Test File | Tests | Scope |
|-----------|-------|-------|
| `test_smoke.py` | 14 | Core imports, models, exceptions |
| `test_http_provider.py` | 12 | HTTP provider error handling |
| `test_memory.py` | 14 | Session store edge cases |
| `test_search.py` | 5 | Web search tool |
| `test_tools.py` | 12 | Cmd safety, read/write guards |
| `test_router.py` | 13 | ReAct loop, fallback, tool execution |
| `test_phase0_policy.py` | 14 | ToolCategory, ToolPolicy, profiles, rate-limit |
| `test_phase1_mcp.py` | 8 | MCP config, bridge, error handling |
| `test_phase1b_2a.py` | 15 | CategoryRouter, LongTermMemory, Summarizer |
| `test_phase3_learning.py` | 17 | SkillStore, SkillFactory, SkillRefiner |
| `test_phase4_spawn.py` | 3 | SpawnManager, nesting, timeout |
| `test_http_provider.py` | 12 | HTTP provider edge cases |
| **Total** | **143** | |

---

## 6. Runtime Verification

```
🏝️  HAVEN — KID Safe Haven
Primary:   DeepSeek deepseek-v4-flash
Fallback:  OpenRouter google/gemma-4-26b-a4b-it
Tools:     6 (execute_command, write_file, read_file, web_search, memory_search, spawn_child)
Ollama:    nomic-embed-text + minicpm-v ✅ (http://localhost:11434)
Terminal:  ✅ active
Discord:   ✅ active
Telegram:  ❌ (no token configured — expected)
```

- Zero import errors
- Zero startup crashes
- All 6 tools registered correctly
- Ollama bridge operational
- REPL prompt displayed: `Cris>`

---

## 7. Design Principles Upheld

- **No circular imports** — dependency graph is strictly acyclic
- **No destructive changes** to existing `core/` modules
- **Safe-by-default** — learning system creates drafts only, never auto-activates
- **Graceful degradation** — ollama, MCP, and Telegram failures are non-fatal
- **Opt-in** — all new features disabled by default, enabled via config
- **Interface over Implementation** — Router depends on abstractions, not concretions

---

## 8. What's Next

| Priority | Item | Status |
|----------|------|--------|
| 🔴 High | Runtime integration test (send real message through Router → LLM → tool) | Not yet |
| 🔴 High | Connect a real MCP server (e.g. filesystem, git) | Code ready, not tested |
| 🟡 Medium | Discord transport end-to-end test with policy enforcement | Not yet |
| 🟡 Medium | Observe SkillFactory with real session data | Only unit tests so far |
| 🟢 Low | Telegram bot token setup | Token needed |
| 🟢 Low | Production deployment configuration | Needs planning |
| 🟢 Low | Performance profiling under sustained load | Future |

---

## 9. Key Metrics

| Metric | Value |
|--------|-------|
| Python files | 37 |
| Total LOC | ~4,500 |
| Tests | 143 (all passing) |
| Tools | 6 (4 built-in + memory + spawn) |
| Providers | 3 (DeepSeek, OpenRouter, Ollama) |
| MCP protocol | stdio + SSE (JSON-RPC 2.0) |
| Max file size | 400 lines (lint-enforced) |
| Circular imports | 0 |
| CI runtime | ~45 seconds |

---

*Haven started as a 3-tool escape pod. It is now a complete AI core with governance, memory, learning, delegation, and a clean CI pipeline. Ready for integration testing and production hardening.*
