# Haven P2+ — Next Steps Workflow

> **Scope:** P2 items (記憶淘汰機制, Config 結構化) + complementary improvements  
> **Phase:** Post-P1 — all P1 items shipped (transport abstraction, concurrent test, health check)  
> **Test baseline:** 534 passed, 4 skipped, 0 failed  
> **GMK constraint:** < 4 GB RAM available to Node, chunk everything > 10 MB / 5,000 lines  

---

## 1. Standardized Specification

### Entities

| Entity | Description | Persisted? |
|--------|-------------|------------|
| Config | Centralised typed configuration (env vars, paths, constants) | `.env` + Python module |
| Memory Eviction | Mechanism to purge old/least-important session memories under RAM pressure | LongTermMemory (files) |
| ResourceMonitor | RAM + CPU threshold checker in pressure.py | Runtime |
| SkillStore | Skill lifecycle (register, activate, inject) | Filesystem |
| ErrorHandler | Graceful degradation paths when providers/resources fail | Runtime |
| IntegrationTest | Real API end-to-end test suite | CI-skipped |

### Decision points

1. **Config 結構化** Must be done first — nearly every other item reads config values.
2. **記憶淘汰機制 + GMK 資源管理** — naturally paired; eviction depends on resource pressure.
3. **Error recovery** — uses circuit breaker (P0) + ResourceMonitor; no hard dependency.
4. **Skill 系統測試** — reads from SkillStore, which reads paths from Config.
5. **Integration 擴充** — requires API keys (already in `.env`), standalone.

### RFC2119 rules

- **Must** — Config 結構化 before Skill 系統測試 (SkillStore reads paths from config)
- **Must NOT** — introduce new env vars without tests and typed defaults
- **Should** — 記憶淘汰 + GMK 資源管理 done as a pair (one eviction strategy, one suite of RAM pressure tests)
- **May** — Error recovery tests be done independently at any time

---

## 2. Pipeline Architecture

### Dependency Graph

```
Config 結構化 ─┬──→ Skill 系統測試
               ├──→ 記憶淘汰機制 ──→ GMK 資源管理測試
               └──→ Integration 擴充 (API keys)
Error recovery ───── standalone
```

### Node Breakdown

| # | Node | Input | Output | Type | Effort |
|---|------|-------|--------|------|--------|
| A | Config 結構化 | Current `.env` + Python constants | `core/config.py` + tests | Deterministic + Tests | Medium |
| B | 記憶淘汰機制 | LongTermMemory class | LRU/TTL eviction + tests | Reasoning + Tests | Low |
| C | GMK 資源管理測試 | ResourceMonitor, crash context | RAM pressure scenarios, crash recovery tests | Tests | Medium |
| D | Error recovery | Circuit breaker, provider chain | Graceful degradation tests | Tests | Medium |
| E | Skill 系統測試 | SkillStore, SkillFactory | Lifecycle tests (register→activate→inject→remove) | Tests | Medium |
| F | Integration 擴充 | Existing integration tests + real API | More end-to-end scenarios | Tests | Low |

### Artifact Schemas

**Config artifact** (Node A output):
```python
@dataclass
class HavenConfig:
    primary_model: str = "deepseek-v4-pro"
    fallback_model: str = "google/gemma-4-26b-a4b-it"
    tertiary_model: str = "seed-2-0-lite"
    memory_dir: Path = Path("data/memory/")
    skill_dir: Path = Path("data/skills/")
    memory_eviction_ttl_days: int = 30
    memory_max_entries: int = 1000
    ram_warning_pct: float = 70.0
    ram_critical_pct: float = 85.0
    discord_token: str = ""
    telegram_token: str = ""
```

**Memory eviction result** (Node B output):
```python
@dataclass
class EvictionReport:
    evicted: int
    retained: int
    freed_bytes: int
    strategy: str  # "lru" | "ttl" | "importance"
```

### HITL Checkpoints

- **[HITL-A]** After Config 結構化 draft: review naming conventions and env var defaults
- **[HITL-B]** After 記憶淘汰策略: choose LRU vs TTL vs importance-based
- **[HITL-D]** Error recovery approach: approve what "graceful degradation" means for Haven

---

## 3. Iteration Plan

### Iteration 1: Config 結構化 + 記憶淘汰機制

**Target:** 2 sessions

| Step | Risk | Mitigation |
|------|------|------------|
| A1: Create `core/config.py` with dataclass | May miss existing env var references | grep all `os.getenv` / `os.environ` across codebase |
| A2: Update `main.py` to use config | Breaking change if wrong | Tests must pass before deploy |
| A3: Config tests | Low (straightforward dataclass test) | — |
| B1: Implement memory eviction in LTM | Choosing wrong strategy | [HITL-B] Review before coding |
| B2: Eviction tests | Timing/ordering | Use deterministic clock mock |

**Test files:** `test_config.py` + `test_memory_eviction.py`

### Iteration 2: GMK 資源管理 + Error recovery

**Target:** 2 sessions

| Step | Risk | Mitigation |
|------|------|------------|
| C1: ResourceMonitor test expansion | Mock `psutil` correctly | Use `unittest.mock.patch` |
| C2: Crash recovery scenarios | Real crash simulation | Use FakeProvider with configurable failure modes |
| D1: Graceful degradation (all providers down) | Missing error handler paths | Walk through Router._execute_tool chain |
| D2: Degradation tests | Edge cases | Cover 0/1/many providers |

**Test files:** `test_resource_gate.py` expansion + `test_error_recovery.py`

### Iteration 3: Skill 系統測試 + Integration 擴充

**Target:** 2 sessions

| Step | Risk | Mitigation |
|------|------|------------|
| E1: SkillStore lifecycle tests | Skill shape may change | Test interface, not internals |
| E2: Skill injection pipeline tests | CategoryRouter dependency | Use fake CategoryRouter |
| F1: Transport integration (real Discord) | Token management | Skip in CI, run manually |
| F2: Full pipeline end-to-end | Slow | Mark `@pytest.mark.slow` |

**Test files:** `test_skill_store.py` + integration test expansion

### Known tacit knowledge risks

1. **Config refactoring** — `main.py` has inline `os.getenv` calls at ~40 locations. Must find them ALL.
2. **Memory eviction** — LTM currently open-ended; eviction may affect existing behaviour. Must measure before/after.
3. **GMK RAM** — `ResourceMonitor` currently uses `psutil.virtual_memory()`. Real GMK WSL2 behaviour may differ from dev machine. Tests should use mock-based.
4. **Skill injection** — Skills are `.py` files loaded dynamically. Tests should use `tmp_path` fixtures, not real skill dirs.

---

## 4. Integration Blueprint

### Required systems

| Node | System | Interface | Auth |
|------|--------|-----------|------|
| A | Filesystem | Python `pathlib` | — |
| B | LongTermMemory | `soul/memory/long_term.py` | — |
| C | `psutil` | `import psutil` | mock in tests |
| D | Provider chain + circuit breaker | `core/router.py` + `core/circuit_breaker.py` | — |
| E | SkillStore | `learning/skill_store.py` | — |
| F | Discord / Telegram | Real bot tokens | `.env` variables |

### HITL thresholds

| Action | Threshold | Pause For |
|--------|-----------|-----------|
| Change existing env var name | Any | Config review |
| Change memory eviction strategy | Any | Strategy review |
| Modify `main.py` init flow | Any | Diff review |
| Add new provider type | Any | Architecture review |

### Test file delivery

```
dev/kid/tests/test_config.py
dev/kid/tests/test_memory_eviction.py
dev/kid/tests/test_error_recovery.py
dev/kid/tests/test_skill_store.py
```
