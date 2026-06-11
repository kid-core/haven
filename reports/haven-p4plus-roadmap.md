# Haven P4+ Roadmap — 未來階段規劃

> 基於：Claude Code 泄露源碼分析 + Haven 現有架構 (P0-P3 done)  
> 日期：2026-06-10  
> 測試基線：724 passed, 0 failed  
> 更新：P4d 合併 /goal + Fable 5 Advisor Pattern  

---

## P4 — 結構重組（低風險，即做）

### P4a: Context 分層提示詞

**現狀：** Router 一句 flat system prompt，所有嘢塞埋一齊

**改：** 五層動態裝配系統

```python
class SystemPromptAssembler:
    def build(self, session_id, role, extra_rules) -> str:
        layers = [
            self._identity_layer(),           # 基礎身份
            self._runtime_layer(session_id),   # Git + 日期 + env
            self._user_rules_layer(extra_rules),  # 長期附加規則
            self._role_layer(role),            # 角色模式
            self._tool_layer(),                # 工具使用指引
        ]
        return "\n\n".join(layers)
```

**目標：** ~15 tests, +1 module (`core/prompt_assembler.py`)
**風險：** 低

---

### P4b: Tools Group 重組

**現狀：** ToolCategory 有 FILES/SYSTEM/WEB/AI/COMMUNICATION/MEMORY/EXTERNAL

**改：** 跟 CC 四大類重組

| 新類別 | 包含 tools | 現狀對應 |
|--------|-----------|----------|
| FILE | read/write/edit/glob/grep | FILES |
| ENV | bash/search/fetch/ollama | SYSTEM + WEB |
| SESSION | ask_user/plan_mode/todo_write | 🔴 未有 |
| COLLAB | sub_agent/mcp_task/skill | EXTERNAL |
| MEDIA | image_gen/music_gen/video_gen | AI |
| MEMORY | memory_read/memory_write | MEMORY |

**目標：** ~5 tests, 極低風險

---

### P4c: Budget Check 基礎設施

**現狀：** Router 有 `max_turns` 但冇 budget check

**改：** `BudgetTracker` dataclass

```python
class BudgetTracker:
    max_budget_usd: float = 0.0
    total_cost: float = 0.0
    
    def record_usage(self, input_tokens, output_tokens):
        cost = input_tokens * INPUT_RATE + output_tokens * OUTPUT_RATE
        self.total_cost += cost
    
    def is_exhausted(self) -> bool:
        return self.max_cost_usd > 0 and self.total_cost >= self.max_cost_usd
```

放入 Router + tracer，每 turn 尾 check

**目標：** ~10 tests, `core/budget.py`
**風險：** 低

---

### P4d: /goal + Advisor Pattern（自主追問）

**現狀：**
- Haven 冇目標追蹤系統，Router 就咁 call provider → execute tool → loop
- Fable 5 嘅 Advisor Pattern 啟示：模型應該先理解需求、唔肯定時 call 更高級 advisor

**改：** 兩個子系統一齊做

#### 子系統 A: `/goal` 目標管理

`core/goal_manager.py` + `core/command_handler.py`

```python
@dataclass
class Goal:
    id: str
    title: str;  description: str
    status: Literal["active", "completed", "cancelled"]
    created_at: float;  completed_at: float | None
    progress: float  # 0.0 - 1.0
    tags: list[str]

class GoalManager:
    def create(...) -> Goal        # /goal add
    def complete(...) -> bool       # /goal done
    def cancel(...) -> bool         # /goal cancel
    def list_active() -> list[Goal] # /goal list
    def status_report() -> str      # /goal status
    def inject_into_context() -> str # prompt layer
```

**流程：**
1. TransportAdapter.handle_message() 偵測 `"/goal"` → command handler
2. GoalManager CRUD → JSON persistence
3. P4a runtime layer inject active goals

#### 子系統 B: Advisor Pattern（Router loop 改造）

Router.process() loop 由一條直線變成三步：

```
┌──────────────────────────────────────────────┐
│  Router.process() loop (C = Executor)         │
│                                                │
│  Phase 1 — Requirement Gathering              │
│    C: 「呢個 task 唔清楚，我問清楚先」         │
│    C: 用 `ask_user` tool 或 call advisor       │
│    → goals 清晰化 → 入 context                │
│                                                │
│  Phase 2 — Execution                          │
│    C: call provider → execute tool → loop      │
│    └── if uncertain at tool result             │
│         → call Advisor (貴價 model, ~500 tok)  │
│         → apply suggestion → continue         │
│                                                │
│  Phase 3 — Verification                        │
│    C: check goal completion                   │
│    → 完成 → /goal done auto                   │
│    → 未完成 → loop back to Phase 2            │
└──────────────────────────────────────────────┘
```

**Advisor call 具體：**
- Executor = primary provider（DeepSeek Flash 等平價模型）
- Advisor = 可配置（依賴 P4c Budget 決定用邊個層級）
- 每個 advisor call ~$0.02（500 tok × $50/M）
- BudgetTracker.record_usage() track 住

**已有基建可重用：**
| 需要 | 已有 |
|------|------|
| JSON persistence | SkillStore pattern |
| Transport dispatch | TransportAdapter.handle_message() |
| Context injection | P4a prompt assembler |
| Provider chain | primary/fallback/tertiary |
| Budget tracking | P4c BudgetTracker |
| Session management | Router session |
| Testing | conftest.py + FakeProvider |

**目標：** ~20 tests, `core/goal_manager.py` + `core/command_handler.py` + `core/advisor.py`
**風險：** 低（邏輯獨立，唔影響現有 flow）

---

## P5 — 變速載入（中等工程）

### P5a: Skills Defer Loading

**現狀：** detect pattern -> generate -> 下次全部 inject

**改：** 兩階段
1. 註冊：name + description -> available list（唔展開）
2. 展開：模型 call `SkillTool("deploy-check")` 先 load

**改：** `learning/skill_factory.py`, `core/category_router.py`, `tools/skill_tool.py`（新 tool）

**目標：** ~20 tests
**風險：** 中

---

## P6 — MCP 支援（大工程）

### P6a: MCP Client + Bridge

```
MCP Server (stdio/HTTP/WS)
    ↓ tools/list + resources/list
core/mcp_client.py  ->  ToolSpec 對象
    ↓
core/mcp_bridge.py  ->  CategoryRouter + ToolRegistry
    ↓
transport/adapter.py
```

| Module | 職責 | ~LOC |
|--------|------|------|
| `core/mcp_client.py` | 連接 server, 拉 schema | 300 |
| `core/mcp_bridge.py` | 轉成 ToolSpec + route | 200 |
| `core/mcp_registry.py` | 管理多 server lifecycle | 150 |

**目標：** ~30 tests
**風險：** 高

---

## 執行順序

```
P4a (Prompt分層) ──→ P4c (Budget) ────→ P4b (Group rename)
    │                  │
    ├── P4d (/goal     └── Budget provide rate for advisor
    │      + Advisor)
    │       ├── P4a runtime layer inject goals
    │       ├── P4c BudgetTracker track advisor cost
    │       └── Router 3-phase loop (gather→exec→verify)
    │
    └──→ P5a (Defer loading) ──→ P6 (MCP)
```

| Phase | 做咩 | +tests | 風險 | 相依 |
|-------|------|--------|------|------|
| P4a | Context 分層提示詞 | ~15 | 低 | — |
| P4b | Tools group 重組 | ~5 | 極低 | — |
| P4c | Budget check infra | ~10 | 低 | — |
| P4d | /goal + Advisor Pattern | ~20 | 低 | P4a + P4c |
| P5a | Skills defer loading | ~20 | 中 | P4a |
| P6 | MCP 支援 | ~30 | 高 | P5a |
| **Total** | | **~100** | | |
