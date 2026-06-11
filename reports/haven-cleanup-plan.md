# Haven 環境整頓與測試改造計畫

> **狀態：** 執行中 · Phase 0 已完成  
> **作者：** KID  
> **日期：** 2026-06-10

---

## 目錄

1. [為甚麼要做](#1-為甚麼要做)
2. [已完成工作](#2-已完成工作)
3. [Phase 剩餘工作](#3-phase-剩餘工作)
4. [改造路線圖](#4-改造路線圖)
5. [附錄](#5-附錄)

---

## 1. 為甚麼要做

Haven 由 Seed 時期開始累積，經歷多次架構重寫（agent.core.loop → dev/kid Router），
但測試和文件結構一直沒跟上。造成兩個具體問題：

### 問題一：測試斷層

```
/tests/                    dev/kid/tests/
  11 files, 5,100 lines       21 files, 3,700 lines
  Global counter pattern       pytest + MockProvider
  test(name, condition)        test_xxx() assertions
  引用舊架構 (已過時)           可跑但覆蓋不全
```

舊測試驗證的是「框架構造成功」（屬性存在、模組可匯入），
不是「框架行為正確」（收到 tool call 會不會執行、crash 後會不會恢復）。

新測試雖然框架正確，但有大片空白：
- Provider fallback chain ─ 0 tests
- Transport layer (Discord/Telegram) ─ 0 tests
- Crash recovery ─ 0 tests
- Security boundary ─ 0 tests
- SkillFactory refinement ─ 0 tests
- Integration (real API) ─ 0 tests

### 問題二：根目錄混亂

根目錄混雜了系統必需檔和純文件，28 個檔案中有 16 個是文件，
增加認知負擔，也容易誤刪。

---

## 2. 已完成工作

### Phase 0a — 文件歸檔 ✅ (2026-06-10)

**目標：** 根目錄只保留系統運作必需的檔案

**搬運清單（16 個文件 → `doc/`）：**

| 原位置 | 新位置 |
|--------|--------|
| `README.md`, `README.txt` | `doc/manual/` |
| `使用說明_v1.0.txt`, `contacts.md` | `doc/manual/` |
| `Haven_architecture_map.*` (3 files) | `doc/technical/` |
| `Haven架構圖.png` | `doc/technical/` |
| `overview_v1.0.txt` | `doc/technical/` |
| `ENVIRONMENTS.md`, `ENVIRONMENTS.txt` | `doc/technical/` |
| `EMERGENCY.md`, `RETIRED.md` | `doc/history/` |
| `Sync_Map.md` | `doc/history/` |
| `Haven_原型文件_v0.2.txt` | `doc/history/` |
| `Haven_說明書_v0.2.txt` | `doc/history/` |
| `dev/CONVENTIONS.md`, `dev/CONVENTIONS_EN.md` | `doc/technical/` |
| `dev/README.md` | `doc/manual/` |
| `dev/potential_upgrade/` (4 files) | `doc/plans/` |

**`doc/` 目錄結構：**

```
doc/
├── README.md          ← 索引目錄
├── manual/            ← 使用者手冊、聯絡資訊
├── technical/         ← 架構圖、開發規約、環境設定
├── plans/             ← 未來升級提案
└── history/           ← 退役記錄、原型文件
```

**根目錄保留（12 個系統必需檔）：**

`.env`, `.gitignore`, `haven_start.sh`, `haven_stop.sh`,
`haven_tmux.sh`, `start_discord.sh`, `start_haven.bat`,
`stop_haven.bat`, `attach_haven.bat`, `haven-discord.service`,
`haven.log`, `sync_log.txt`

### Phase 0b — 測試策略文件 ✅ (2026-06-10)

**產出：** `reports/testing-strategy.md`（完整測試設計文件）

**核心架構：**

```
三層測試金字塔

            ╱╲
           ╱  ╲           Integration (real API)        ~5 tests
          ╱──────╲
         ╱        ╲       Component (behavior tests)   ~30 tests
        ╱────────────╲
       ╱              ╲    Unit (pure logic)            ~80 tests
      ╱──────────────────╲
```

**各層重點：**

| 層 | 內容舉例 | 測試數 | CI 執行 |
|----|---------|--------|---------|
| Unit | `_is_safe`, `PressureLevel`, `CrashJournal`, Models | 80+ | ✅ |
| Component | FakeProvider + Router, Fallback, ResourceGate, TaskManager | 30+ | ✅ |
| Integration | 真實 DeepSeek API round-trip | 5 | ❌ nightly |

**關鍵設計：FakeProvider 狀態機**

```python
class FakeProvider(BaseProvider):
    """不是 mock，是可控的 LLM 模擬器。
    可以 preset N 次呼叫的回應序列，然後 assert
    Router 的行為（call_count, tool execution, turn limit）。
    """
    def add_response(self, content=None, tool_calls=None):
        self._responses.append(ProviderResponse(...))

    async def chat_completion(self, messages, tools=None, **kwargs):
        self.call_count += 1
        captured = self._responses.pop(0)
        return captured
```

**路線圖（7 Phase）：**

```
Phase 0: 基礎設施建立     (2-3h)  ← 進行中
Phase 1: 工具層單元測試    (3h)
Phase 2: Router + Fallback (4h)
Phase 3: Resource + Task    (3h)
Phase 4: Persistence        (3h)
Phase 5: Messaging + Transport (3h)
Phase 6: Security + Integration (3h)
Phase 7: 舊測試退休        (選項)
```

**總測試目標：** 115 個行為測試，CI 執行約 30s

---

## 3. Phase 剩餘工作

### Phase 1: 工具層單元測試

```
預計時間：3h | test count: ~30
```

- [ ] `test_tools.py` 補 `cmd._is_safe` / `_translate_path` 完整覆蓋（邊界案例）
- [ ] `test_tools.py` 補 `read._is_path_allowed`
- [ ] `test_tools.py` 補 `write._is_path_allowed`
- [ ] 新增 `test_models.py` — ProviderResponse, TaskRecord, ScheduleRecord
- [ ] 新增 `test_pressure.py` — PressureLevel 閾值、Ram cache 行為
- [ ] 新增 `test_crash_journal.py` — 寫入、損毀檔處理、檔案 bounded

### Phase 2: Router + Provider Fallback

```
預計時間：4h | test count: ~20
```

- [ ] 重構 `test_router.py` 的 FakeProvider 為完整狀態機
- [ ] 補 provider fallback chain 測試（primary fail → secondary, all fail → error）
- [ ] 補 error handling（tool timeout, policy block, tool not found）
- [ ] 新增 `test_category_router.py` — 三種 execution mode (INLINE/AI_PROXY/EXTERNAL)

### Phase 3: ResourceGate + TaskManager + Scheduler

```
預計時間：3h | test count: ~15
```

- [ ] 補 `test_resource_gate.py` 的 auto-chunking
- [ ] 補 RED→retry→GREEN 順序測試
- [ ] 新增 `test_task_manager.py` — lifecycle, timeout, cancel, concurrent
- [ ] 補 `test_scheduler.py` — at/every/cron 行為, persistence

### Phase 4: Persistence + Crash Recovery

```
預計時間：3h | test count: ~10
```

- [ ] 補 skill_store reload 測試（tempdir 模擬重啟）
- [ ] 補 crash 寫入測試（partial write → graceful recover）
- [ ] 補 session restore 測試（interrupted 任務標記）

### Phase 5: Messaging + Transport

```
預計時間：3h | test count: ~10
```

- [ ] 新增 `test_message_bus.py` — priority, overflow, routing
- [ ] 新增 `test_transport.py` — user whitelist, DM vs channel
- [ ] 新增 test fixtures 用於 transport 層模擬

### Phase 6: Security + Integration

```
預計時間：3h | test count: ~10
```

- [ ] 新增 `test_security.py` — injection, rate limit, data leakage
- [ ] 新增 `tests/integration/` — 5 個真實 API 測試
- [ ] 確認 CI markers (`unit`, `component`, `integration`, `slow`) 正確運作

### Phase 7 (選項): 舊測試退休

```
預計時間：1h
```

- [ ] 確認新測試覆蓋舊測試核心驗證點
- [ ] 標記 `/tests/` 為 retired
- [ ] Migration note 記錄對應關係

---

## 4. 改造路線圖

```
                現在
                 │
                 ▼
      ┌─────────────────────┐
      │ Phase 0 DONE        │  ← 今天完成
      │ 文件歸檔 + 測試策略  │
      └────────┬────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
  Phase 1          Phase 2
  工具單元測試      Router 行為
   (3h, ~30)        (4h, ~20)
       │               │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │ Phase 3       │
       │ Resource+Task │
       │   (3h, ~15)   │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │ Phase 4       │
       │ Persistence   │
       │   (3h, ~10)   │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │ Phase 5       │
       │ Messaging+Tr. │
       │   (3h, ~10)   │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │ Phase 6       │
       │ Security+Int. │
       │   (3h, ~10)   │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │ Phase 7 (opt) │
       │ 退休舊測試    │
       │   (1h)        │
       └───────────────┘
```

**預估總時間：** ~23h（Phase 0-6）
**最終產出：** 115+ tests, CI 30s, 全覆蓋核心行為

---

## 5. 附錄

### A. 現有測試覆蓋地圖

| 模組 | 現有 tests | 應有 tests | 差距 |
|------|-----------|-----------|------|
| `core/router.py` | ~10 | ~20 | 🔴 |
| `core/resource_gate.py` | ~15 | ~20 | 🟡 |
| `core/http_provider.py` | ~5 | ~5 | ✅ |
| `core/tool_registry.py` | ~3 | ~8 | 🟡 |
| `core/category_router.py` | ~2 | ~6 | 🔴 |
| `core/task_manager.py` | ~0 | ~8 | 🔴 |
| `core/scheduler.py` | ~0 | ~8 | 🔴 |
| `core/message_bus.py` | ~0 | ~6 | 🔴 |
| `core/crash_journal.py` | ~0 | ~5 | 🔴 |
| `tools/` | ~15 | ~20 | 🟡 |
| `transport/` | ~0 | ~8 | 🔴 |
| `learning/` | ~10 | ~12 | 🟢 |

### B. 文件歸檔前後對比

```
Before (28 entries in root)          After (12 entries in root)
─────────────────────────────         ────────────────────────────
.env                                 .env
.gitignore                           .gitignore
README.md                            attach_haven.bat
README.txt                           dev/
EMERGENCY.md                         doc/           ← 新
ENVIRONMENTS.md                      haven-discord.service
ENVIRONMENTS.txt                     haven_start.sh
Haven_architecture_map.png           haven_stop.sh
Haven_architecture_map.svg           haven_tmux.sh
Haven_architecture_map_zh.svg        scripts/
Haven_原型文件_v0.2.txt              start_discord.sh
Haven_說明書_v0.2.txt                start_haven.bat
Haven架構圖.png                      stop_haven.bat
RETIRED.md                           tests/
Sync_Map.md                          (其餘目錄不變)
attach_haven.bat
contacts.md
dev/
haven-discord.service
haven_start.sh, _stop.sh, _tmux.sh
long_term_memory/
overview_v1.0.txt
start_discord.sh
start_haven.bat
stop_haven.bat
sync_log.txt
tests/
使用說明_v1.0.txt
workspace_memory/
```
