# Haven Testing Strategy

> **Status:** Draft · **Last updated:** 2026-06-10  
> **Scope:** dev/kid/ codebase (Phase 0–9), legacy tests in /tests/  
> **Author:** KID

---

## 1. 現狀診斷

### 1.1 兩套測試的斷層

Haven 目前有兩套完全獨立的測試：

| 位置 | 行數 | 框架 | 風格 | 狀態 |
|------|------|------|------|------|
| `dev/kid/tests/` (21 files) | ~3,700 | **pytest** ✅ | MockProvider pattern | 可跑但覆蓋不全 |
| `/tests/` (11 files) | ~5,100 | **Global counter** ❌ | `test(name, condition)` | 引用舊架構，已過時 |

**核心問題：** 第二套 5,000+ 行測試驗證的是「框架構造成功」而非「框架行為正確」——它們斷言屬性存在、模組可匯入，卻從未測試 Router 收到 tool call 後會不會真的執行工具、CrashJournal 寫入壞檔後會不會優雅恢復。

### 1.2 目前測試覆蓋盲區

```
┌─ dev/kid 現有測試覆蓋 ─────────────────────┐
│ ✅ Router (MockProvider)    → 386 lines     │
│ ✅ ResourceGate             → 521 lines     │
│ ✅ Tools (cmd, read, write) → 233 lines     │
│ ✅ Scheduler                → 263 lines     │
│ ✅ MessageBus               → 219 lines     │
│ ✅ Persistence              → 214 lines     │
│ ✅ Memory subsystem         → 204 lines     │
│ ──── 以下接近空白 ────                       │
│ ❌ Provider fallback chain  → 0             │
│ ❌ Transport layer (Discord) → 0             │
│ ❌ Crash recovery           → 0             │
│ ❌ Security boundary        → 0             │
│ ❌ CategoryRouter routing   → partial       │
│ ❌ SkillFactory refinement  → 0             │
│ ❌ Integration (real API)   → 0             │
└──────────────────────────────────────────┘
```

---

## 2. 測試金字塔（Haven 版）

```
            ╱╲
           ╱  ╲           Integration (real API)
          ╱    ╲          @pytest.mark.integration  ~5 tests
         ╱──────╲
        ╱        ╲        Component / Behaviour
       ╱          ╲       @pytest.mark.component    ~30 tests
      ╱────────────╲
     ╱              ╲     Unit (pure logic)
    ╱                ╲    @pytest.mark.unit         ~80 tests
   ╱──────────────────╲
```

**各層定義：**

- **Unit** — 單一 function / class，無外部相依（`_is_safe`, `PressureLevel.from_percent`, `_translate_path`）
- **Component** — 多個單元協作，但 provider/db 等用 mock 控制（Router + FakeProvider, ResourceGate + fake psutil）
- **Integration** — 真實相依（真實 LLM API，真實檔案系統），CI 預設略過

### 測試總量目標：115 ± 15 tests（比舊系統 260 個淺測試更有價值）

---

## 3. 測試分層詳細設計

### Layer 1: 純邏輯單元測試 (Unit)

**位置：** `dev/kid/tests/test_*.py`  
**標記：** `@pytest.mark.unit`  
**目標：** 80+ tests

#### 3.1 Command Tool 安全檢查

```
dev/kid/tools/cmd.py 中的純函數
────────────────────────────────
_is_safe(cmd)        → (bool, reason)
_translate_path(cmd) → str
```

| Test | 驗證內容 |
|------|---------|
| `test_blocks_dangerous_commands` | `rm`, `mv`, `dd`, `mkfs`, `sudo` 全部阻擋 |
| `test_allows_safe_commands` | `ls`, `cat`, `python`, `git status` 全部允許 |
| `test_blocks_shell_metachars` | ``;`, `|`, `$()`, `\`` ``, `&&` 全部阻擋 |
| `test_rejects_empty_command` | 空字串、純空白 → 拒絕 |
| `test_translates_windows_paths` | `Z:\Haven\script.py` → `/mnt/z/Haven/script.py` |
| `test_handles_mixed_paths` | 命令中混用 Linux 和 Windows 路徑 |
| `test_preserves_non_path_text` | 非路徑部分不受 `_translate_path` 影響 |

#### 3.2 ProviderResponse / Models

```
dev/kid/core/models.py 中的 Pydantic models
────────────────────────────────────────────
ProviderResponse, TaskRecord, ScheduleRecord, etc.
```

| Test | 驗證內容 |
|------|---------|
| `test_provider_response_content` | content + tool_calls 互斥 |
| `test_task_record_defaults` | uuid 自動生成，status 預設 PENDING |
| `test_schedule_status_enum` | ACTIVE/PAUSED/COMPLETED/CANCELLED 行為 |
| `test_task_status_transitions` | 不允許 PENDING → COMPLETED（跳過 RUNNING） |

#### 3.3 PressureLevel / ResourceMonitor

```
dev/kid/core/resource_gate.py
─────────────────────────────
PressureLevel.from_percent(pct)
ResourceMonitor.check_ram()
```

| Test | 驗證內容 |
|------|---------|
| `test_pressure_level_thresholds` | <50 GREEN, 50-69 YELLOW, 70-84 RED, ≥85 CRITICAL |
| `test_ram_cache_hits_reduce_calls` | 2s cache TTL 內重複呼叫不重新檢查 |
| `test_ram_cache_expiry` | 超過 TTL 後重新檢查 |
| `test_disk_threshold` | Disk > 90% 回傳對應壓力 |

#### 3.4 TaskComplexityEstimator

| Test | 驗證內容 |
|------|---------|
| `test_estimates_by_token_count` | 不同 token 量對應不同 complexity tier |
| `test_estimates_by_tool_count` | 工具數量影響 complexity |
| `test_estimates_minimum_floor` | 永遠 >= 最低 complexity |

#### 3.5 CrashJournal

| Test | 驗證內容 |
|------|---------|
| `test_write_and_read_crash` | 寫入後可正確讀回 |
| `test_handles_corrupted_file` | JSON decode 失敗 → graceful fallback |
| `test_clear_after_recovery` | 恢復成功後自動清空 |
| `test_bounded_file_size` | 日誌檔案不無限增長 |

#### 3.6 工具參數 Schema

```
依賴：@tool decorator 自動生成 JSON Schema
```

| Test | 驗證內容 |
|------|---------|
| `test_every_tool_has_unique_name` | 名稱不重複 |
| `test_every_tool_has_description` | description 不為空 |
| `test_parameters_match_handler_signature` | schema 參數與 handler 參數一致 |
| `test_categories_are_valid` | category 屬於已知 ToolCategory |

---

### Layer 2: 元件行為測試 (Component)

**位置：** `dev/kid/tests/test_*.py`  
**標記：** `@pytest.mark.component`  
**目標：** 30 tests

#### 2.1 FakeProvider（測試基礎設施）

**關鍵設計原則：** 用一個可控的狀態機 FakeProvider 取代真實 LLM，預先設定 N 次呼叫的回應序列，然後驗證 Router 的行為。

```python
class FakeProvider(BaseProvider):
    """Controllable fake: preset response sequence, verify call patterns.

    Not a mock — it's a state machine that simulates LLM behavior
    deterministically.
    """

    def __init__(self):
        self.call_count = 0
        self._responses: list[ProviderResponse] = []
        self.last_messages: list[dict] | None = None

    def add_response(self, content=None, tool_calls=None, reasoning=None):
        self._responses.append(
            ProviderResponse(
                content=content,
                tool_calls=tool_calls,
                reasoning_content=reasoning,
            )
        )

    async def chat_completion(self, messages, tools=None, **kwargs):
        self.call_count += 1
        captured = self._responses.pop(0)
        self.last_messages = messages
        return captured
```

#### 2.2 Provider Fallback Chain

```
dev/kid/core/router.py 的 provider chain 邏輯
─────────────────────────────────────────────
Router._try_providers()
```

| Test | 驗證內容 | Priority |
|------|---------|----------|
| `test_primary_failure_falls_to_secondary` | Primary HTTP 500 → secondary 接手 | 🔴 Critical |
| `test_primary_returns_text_immediately` | Primary 回文字 → 不叫 secondary | 🔴 Critical |
| `test_all_providers_fail_returns_error` | 全掛 → 回傳錯誤訊息 | 🔴 Critical |
| `test_secondary_takes_over_on_timeout` | Primary timeout → secondary 上場 | 🟡 Important |
| `test_provider_chain_respects_order` | provider list 順序被遵守 | 🟡 Important |

#### 2.3 Router ReAct Loop

```
dev/kid/core/router.py
──────────────────────
Router.process()
```

| Test | 驗證內容 | Priority |
|------|---------|----------|
| `test_text_response_ends_loop` | LLM 直接回文字 → 不執行工具 | 🔴 Critical |
| `test_single_tool_call_executed` | LLM call tool → 執行 → 結果回 LLM | 🔴 Critical |
| `test_multi_turn_conversation` | 連續問答，context 正確累積 | 🔴 Critical |
| `test_max_turns_exceeded` | 超過 max_turns → 終止並提示 | 🔴 Critical |
| `test_tool_execution_error_reported_to_llm` | 工具拋錯 → 錯誤傳回 LLM 而非 crash | 🔴 Critical |
| `test_tool_output_wrapping` | wrap_output 格式正確送達 | 🟡 Important |
| `test_empty_history_is_empty_list` | 新 session history = [] | 🟡 Important |
| `test_system_prompt_injected_on_first_turn` | system prompt 只在首輪插入 | 🟡 Important |
| `test_tool_not_found_returns_error` | LLM call 不存在工具 → 回傳錯誤 | 🟡 Important |
| `test_policy_blocked_tool` | Policy 擋工具 → 錯誤傳回 LLM | 🟡 Important |
| `test_tool_timeout_does_not_hang` | 工具執行超時 → 優雅中斷 | 🟢 Nice |

#### 2.4 CategoryRouter

```
dev/kid/core/category_router.py
────────────────────────────────
CategoryRouter.route()
```

| Test | 驗證內容 |
|------|---------|
| `test_inline_tools_execute_directly` | FILES, SYSTEM, WEB → inline |
| `test_ai_proxy_tools_route_to_provider` | AI category → provider proxy |
| `test_external_tools_delegate_to_mcp` | EXTERNAL category → MCP bridge |
| `test_unknown_category_raises` | 未定義 category → 報錯 |

#### 2.5 ResourceGate Decorator

```
dev/kid/core/resource_gate.py
──────────────────────────────
@resource_gate decorator
```

| Test | 驗證內容 | Priority |
|------|---------|----------|
| `test_green_ram_executes_normally` | GREEN → 正常執行 | 🔴 Critical |
| `test_critical_ram_raises_error` | CRITICAL → ResourceBusyError | 🔴 Critical |
| `test_red_ram_delays_then_retries` | RED → 等 3s → 重試 | 🔴 Critical |
| `test_auto_chunking_large_data` | > threshold → 自動分批 | 🟡 Important |
| `test_yellow_ram_logs_warning` | YELLOW → log warning 但放行 | 🟡 Important |
| `test_chunk_callback_called_per_chunk` | 每 chunk 有 callback 通知 | 🟢 Nice |

#### 2.6 TaskManager

```
dev/kid/core/task_manager.py
─────────────────────────────
TaskManager
```

| Test | 驗證內容 |
|------|---------|
| `test_create_task_returns_id` | 建立成功回傳 task_id |
| `test_task_lifecycle_pending_to_completed` | PENDING → RUNNING → COMPLETED |
| `test_task_timeout_marks_timed_out` | 超時 → TIMED_OUT |
| `test_cancel_task_marks_cancelled` | 取消 → CANCELLED |
| `test_list_active_tasks` | 只回傳未完成任務 |
| `test_concurrent_tasks_do_not_interfere` | 平行任務隔離 |

#### 2.7 Scheduler

```
dev/kid/core/scheduler.py
──────────────────────────
Scheduler
```

| Test | 驗證內容 |
|------|---------|
| `test_at_schedule_fires_once` | at → 準時觸發一次 |
| `test_every_schedule_repeats` | every → 間隔重複 |
| `test_cron_expression` | cron → 按表達式觸發 |
| `test_schedule_persists_across_restart` | 重啟後排程仍存在 |
| `test_pause_and_resume` | 暫停不觸發，恢復繼續 |
| `test_invalid_cron_raises` | 錯誤表達式 → InvalidCronExpressionError |

#### 2.8 MessageBus

```
dev/kid/core/message_bus.py
────────────────────────────
MessageBus
```

| Test | 驗證內容 |
|------|---------|
| `test_send_and_receive` | 發送 → 接收成功 |
| `test_priority_inversion` | ALERT 插隊到 NORMAL 前面 |
| `test_overflow_drops_oldest` | 超過容量 → 丟棄最舊 |
| `test_receive_timeout_returns_none` | 空佇列 + timeout → None |
| `test_routing_to_correct_task` | Task A 不會收到 Task B 的訊息 |

#### 2.9 SkillStore / SkillFactory

```
dev/kid/learning/skill_store.py
dev/kid/learning/skill_factory.py
```

| Test | 驗證內容 |
|------|---------|
| `test_create_and_retrieve_skill` | 建立 → 可讀回 |
| `test_skill_lifecycle_draft_to_active` | DRAFT → ACTIVE → DEPRECATED |
| `test_skill_version_increments` | 更新後 version +1 |
| `test_skill_survives_store_reload` | 重開 store 資料仍在（tempfile） |
| `test_audit_trail_tracks_changes` | 每次修改有記錄 |
| `test_deprecated_skills_excluded_from_context` | 已棄用不被注入 |
| `test_skill_refinement_creates_new_version` | refine → 新版本 + 舊保留 |
| `test_corrupt_store_does_not_crash` | 損毀檔 → 優雅復原 |

#### 2.10 Persistence / Crash Recovery

```
dev/kid/soul/memory/session_store.py
dev/kid/soul/memory/long_term.py
dev/kid/core/crash_journal.py
```

| Test | 驗證內容 | Priority |
|------|---------|----------|
| `test_session_restore_after_crash` | 中斷任務標記為 INTERRUPTED | 🔴 Critical |
| `test_crash_during_write_doesnt_corrupt` | 寫入中 crash → 原始檔不受影響 | 🔴 Critical |
| `test_long_term_memory_persists` | 記憶寫入 → 重啟 → 仍在 | 🟡 Important |
| `test_session_expiry_cleanup` | 過期 session 被清理 | 🟡 Important |
| `test_memory_search_respects_boundary` | 搜尋不越界洩漏 | 🟡 Important |

---

### Layer 3: 整合測試（Integration）

**位置：** `dev/kid/tests/test_integration/`  
**標記：** `@pytest.mark.integration`  
**目標：** 5 tests  
**CI 中預設略過：** `pytest -m "not slow and not integration"`

| Test | 驗證內容 |
|------|---------|
| `test_simple_text_response` | 真實 DeepSeek 對「Say hello」回文字而非工具 |
| `test_tool_selection_accuracy` | LLM 正確選擇工具（read → write 序列） |
| `test_fallback_works_end_to_end` | 故意讓 primary 回 401 → secondary 接手 |
| `test_long_running_task_with_heartbeat` | 長時間任務中 heartbeat 保持 alive |
| `test_crash_and_recover` | 模擬 crash → 重啟 → 任務恢復 |

**整合測試原則：**
- 使用真實 API，但最小化 token 消耗
- 每次測試**不超過 1 次 round-trip**
- 測試結束時必須 cleanup（刪除建立的臨時檔案）
- 不在 CI 中自動執行，標記為 `@pytest.mark.slow` + `@pytest.mark.integration`

---

## 4. 安全測試（獨立維度）

安全不是一個 layer，是**橫跨所有 layer 的檢查點**。建議的測試：

### 4.1 Tool Injection

```
散布在 unit 和 component 層
─────────────────────────────
```

| Test | 層級 | 驗證內容 |
|------|------|---------|
| `test_cannot_bypass_permission_via_tool_name` | Component | 偽造 tool name（`read_file; rm -rf`）→ 拒絕 |
| `test_tool_policy_enforces_rate_limit` | Unit | 超過 rate limit → 阻擋 |
| `test_disabled_tools_not_in_openai_schema` | Unit | policy disabled → schema 不包含 |

### 4.2 Transport Security

| Test | 層級 | 驗證內容 |
|------|------|---------|
| `test_discord_only_responds_to_allowed_users` | Component | 白名單過濾正確 |
| `test_telegram_authorization` | Component | Telegram user id 驗證 |
| `test_terminal_noop_in_non_interactive` | Component | 非互動模式不執行命令 |

### 4.3 Data Leakage

| Test | 層級 | 驗證內容 |
|------|------|---------|
| `test_sensitive_data_not_logged` | Component | API key, token 不入 log |
| `test_tool_history_redacts_sensitive_args` | Component | 敏感參數不記錄 |
| `test_memory_search_respects_scope` | Component | 跨 session 搜尋不洩漏 |

---

## 5. 測試基礎設施

### 5.1 共用的 Fixtures（放 conftest.py）

```python
# dev/kid/tests/conftest.py

@pytest.fixture
def fake_provider():
    """A clean FakeProvider with no preset responses."""
    return FakeProvider()

@pytest.fixture
async def router(fake_provider):
    """Router with one FakeProvider and a full tool registry."""
    registry = get_default_registry()
    return Router(registry, [fake_provider])

@pytest.fixture
def tmp_skill_store(tmp_path):
    """SkillStore backed by a temp directory — auto cleaned up."""
    return SkillStore(storage_dir=tmp_path / "skills")

@pytest.fixture
def crash_journal(tmp_path):
    """CrashJournal backed by a temp file."""
    return CrashJournal(storage_path=str(tmp_path / "crash.json"))
```

### 5.2 Marker Registry

在 `pyproject.toml` 或 `pytest.ini` 註冊自訂 markers：

```ini
[tool.pytest.ini_options]
markers = [
    "unit: Pure logic tests, no dependencies",
    "component: Multi-unit tests with mocked dependencies",
    "integration: Tests using real LLM APIs (skip in CI)",
    "slow: Tests that take >5 seconds",
    "security: Security boundary tests",
    "persistence: Tests covering crash recovery",
]
asyncio_mode = "auto"
```

### 5.3 CI 執行目標

```yaml
# .github/workflows/ci.yml (current: already close to this)
pytest tests/ -m "not slow and not integration" -q --tb=short
```

```yaml
# 可選：nightly full suite
pytest tests/ -q --tb=short   # 含整合測試
```

---

## 6. 路線圖

### Phase 0: 基礎設施建立（預估 2-3h）

- [ ] 補齊 `conftest.py` 共用 fixtures（FakeProvider, tmp_skill_store, crash_journal）
- [ ] 在 `pyproject.toml` 註冊 `unit`/`component`/`integration`/`slow`/`security` markers
- [ ] 確認 CI 只跑 unit + component（排除 integration, slow）
- [ ] 將 `/tests/` 舊測試標記 deprecated，不動它們

### Phase 1: 工具層單元測試（預估 3h，~30 tests）

- [ ] `test_tools.py` 補齊 `cmd._is_safe` / `_translate_path` 完整覆蓋
- [ ] `test_tools.py` 補 `read._is_path_allowed` / `write._is_path_allowed`
- [ ] 新增 `test_models.py` — ProviderResponse, TaskRecord, ScheduleRecord
- [ ] 新增 `test_pressure.py` — PressureLevel 閾值、RAM cache
- [ ] 新增 `test_crash_journal.py` — 寫入、損毀檔處理、bound 限制

### Phase 2: Router + Provider Fallback（預估 4h，~20 tests）

- [ ] 更新 `test_router.py` 的 FakeProvider 為完整狀態機（支援 preset sequence）
- [ ] 補 `test_router.py` 中的 provider fallback chain 測試
- [ ] 補 `test_router.py` 的 error handling 測試（tool timeout, policy block）
- [ ] 新增 `test_category_router.py` — 三種 execution mode

### Phase 3: ResourceGate + TaskManager（預估 3h，~15 tests）

- [ ] 補 `test_resource_gate.py` 的 auto-chunking 測試
- [ ] 補 `test_resource_gate.py` 的 RED→retry→GREEN 測試
- [ ] 新增 `test_task_manager.py` — lifecycle, timeout, cancel, concurrent
- [ ] 新增 `test_scheduler.py` — at/every/cron 行為測試

### Phase 4: Persistence + Crash Recovery（預估 3h，~10 tests）

- [ ] 補 `test_persistence.py` — skill_store reload, session restore, long-term memory
- [ ] 補 crash recovery 測試（`test_crash_during_write_doesnt_corrupt`）
- [ ] 補 session restore 測試（interrupted task marking）

### Phase 5: Messaging + Transport（預估 3h，~10 tests）

- [ ] 新增 `test_message_bus.py` — priority, overflow, routing
- [ ] 新增 `test_transport_discord.py` — user whitelist, DM vs channel
- [ ] 新增 `test_transport_telegram.py` — authorization

### Phase 6: Security + Integration（預估 3h，~10 tests）

- [ ] 新增 `test_security.py` — injection, rate limit, data leakage
- [ ] 新增 `tests/integration/` — 最多 5 個真實 API 測試
- [ ] 確認 CI markers 正確過濾

### Phase 7 (Optional): 舊測試退休

- [ ] 確認新測試覆蓋了舊測試的核心驗證點
- [ ] 將 `/tests/` 標記為 retired
- [ ] 寫一份 migration note 記錄對應關係

---

## 7. 執行指令速查

```bash
# 日常開發（預設，跳過慢和整合）
cd dev/kid && python -m pytest tests/ -q --tb=short

# 僅 unit tests
python -m pytest tests/ -m unit -v

# 僅 component tests
python -m pytest tests/ -m component -v

# 安全測試
python -m pytest tests/ -m security -v

# 整合測試（需要真實 API key）
python -m pytest tests/ -m integration -v

# 詳細失敗輸出
python -m pytest tests/ -v --tb=long

# 含 coverage
python -m pytest tests/ --cov=core --cov=tools --cov=learning --cov=soul --cov=transport

# CI 等同
python -m pytest tests/ -m "not slow and not integration" -q --tb=short
```

---

## 8. 測試撰寫規範

### 8.1 檔案命名

```
test_<module_name>.py       # 單一模組
test_<feature>.py           # 跨模組功能
tests/integration/test_*.py # 整合測試
```

### 8.2 Class 命名

```python
# 按功能分組
class TestCmdSafety:        # unit: cmd 安全檢查
class TestRouterBehavior:   # component: Router 行為
class TestProviderFallback: # component: fallback chain
class TestResourceGate:     # component: resource gate decorator
```

### 8.3 測試方法命名

```
test_<verb>_<condition>_<expected>
```

```python
def test_blocks_dangerous_commands(self):
def test_allows_safe_commands(self):
def test_translates_windows_paths(self):
def test_ram_green_executes_normally(self):
def test_primary_failure_falls_to_secondary(self):
```

### 8.4 Assertion 風格

```python
# ✅ 好
assert result == "expected"
assert "FILE_NOT_FOUND" in tool_result[0]["content"]
assert provider.call_count == 2
assert len(results) > 0

# ❌ 不好
assert result  # 不明確
assert True == result  # 多餘
```

### 8.5 測試隔離原則

- 每個測試獨立，不依賴執行順序
- 外部資源用 pytest fixture + tmp_path 管理
- 非必要不 mock filesystem — 用 `tmp_path` 建立真實暫存目錄
- FakeProvider 取代真實 LLM，除非整合測試

---

## 9. 風險與減少

| 風險 | 緩解 |
|------|------|
| 舊測試 5,100 行沒有直接等同的新測試 | Phase 1-2 的 ~50 個新 test 已 cover 核心行為；遺留測試不刪，標記 deprecated |
| CI 時間隨測試增長 | 分層 markers 確保 CI 只跑 unit + component（< 30s） |
| FakeProvider 偏離真實 LLM 行為 | Layer 3 整合測試（真實 API）作為校正 |
| 資源測試依賴真實 RAM 狀態 | 用 `unittest.mock.patch` mock `ResourceMonitor.check_ram` |
| 團隊不習慣行為測試 | 本文件作為 onboarding doc + code review checklist |

---

## 10. 覆蓋目標總結

| 層級 | 測試數 | 執行時間 (est.) | CI 執行 |
|------|--------|-----------------|---------|
| Unit | 80+ | < 10s | ✅ |
| Component | 30+ | < 20s | ✅ |
| Integration | 5 | ~30s | ❌ (nightly) |
| **總計** | **115+** | **< 1min** | CI: ~30s |

> 115 個行為測試 > 260 個淺測試。品質不是數量。
