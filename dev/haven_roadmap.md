# Haven 進化計畫：借鑑 Hermes 與 OpenClaw 的設計理念

建立日期：2026-05-29
最後更新：2026-05-30 (Phase 0-4 全部完成 ✅)
作者：KID
討論：#haven-dev

---

## 一、為什麼要參考 Hermes & OpenClaw

Haven 的定位是輕量可靠的備援 AI 核心。兩個系統各自有值得學習的點：

### Hermes (Nous Research, 2026.2)

| 特性 | Hermes | 目前的 Haven |
|------|--------|-------------|
| 語言 | Python | Python ✅ |
| 長期運行 | ✅ 原生設計 | ✅ 備援系統本質 |
| 持久化記憶 | ✅ 跨 session 累積 | ❌ 尚未實現 |
| 自我改進 | ✅ 自動寫 skill | ❌ 尚未實現 |
| 低配硬體 | ✅ $5 VPS | ✅ 目標相同 |

但**不是照抄**。Hermes 有 4 Critical + 9 High 安全漏洞，預設全開放。學理念，不學執行。

### OpenClaw

| 特性 | OpenClaw | 目前的 Haven |
|------|----------|-------------|
| 執行環境 | Node.js | Python ✅ |
| 工具生態 | 100+ 內建工具 | 4 個工具 (cmd/read/write/search) |
| Tool Policy | ✅ allow/deny, profile, sandbox | ❌ 全開模式 |
| MCP 支援 | ✅ 可接任意第三方 | ❌ 無 |
| Skills 指令包 | ✅ SKILL.md 載入 prompt | ❌ 無 |
| 工具分類 | ✅ 8+ categories | ❌ flat list |
| 子任務委派 | ✅ sessions_spawn | ❌ 無 |
| Plugin 生態 | ✅ 13,700+ skills | ❌ 無 |
| 持久化記憶 | ✅ memory_search + 索引 | ❌ Phase 1 規劃中 |
| 低配友善 | ❌ 較重 | ✅ 目標輕量 |

**關鍵觀察：**
- Haven 的 tool core（@tool decorator + ToolRegistry）架構比 OpenClaw 的 bundle 更乾淨
- 差距在治理層、生態系、擴充機制
- 可以用 1/10 程式碼做到 OpenClaw 80% 的工具能力

---

## 二、核心改造方向（由淺入深）

### Phase 0 — 工具治理層（Priority: 最高，MVP 之後立即做）

**Haven 現狀：**
工具註冊了就能用，沒有權限控制、沒有分類、沒有審批閘門。

**目標改造：**

```
kid/tools/
├── __init__.py
├── cmd.py
├── write.py
├── read.py
├── search.py
├── policy.py              ← 新增：工具政策層
│   ├── ToolPolicy         # enable/disable 閘門
│   ├── ToolCategory       # 分類標籤
│   └── ToolProfile        # 按情境的預設規則
└── categories.py          ← 新增：工具分類定義
```

**設計概念：**

```python
from enum import Enum, auto

class ToolCategory(Enum):
    FILES = auto()      # read, write, edit
    SYSTEM = auto()     # cmd, process
    WEB = auto()        # search, fetch
    AI = auto()         # image, music, video gen
    COMMUNICATION = auto()  # message, notification
    MEMORY = auto()     # memory ops


class ToolPolicy:
    """每工具的閘門設定。"""
    def __init__(self, *, enabled: bool = True,
                 require_confirm: bool = False,
                 rate_limit: float | None = None,
                 timeout: float | None = None):
        self.enabled = enabled
        self.require_confirm = require_confirm  # 危險操作需 confirm
        self.rate_limit = rate_limit
        self.timeout = timeout


class ToolProfile:
    """按 session/channel 的工具可見預設。"""
    rules: dict[str, bool]  # tool_name → enabled
```

**@tool decorator 擴充：**

```python
@tool(
    name="execute_command",
    category=ToolCategory.SYSTEM,
    policy=ToolPolicy(require_confirm=True, timeout=30.0),
)
async def cmd(...): ...

@tool(
    name="write_file",
    category=ToolCategory.FILES,
    policy=ToolPolicy(require_confirm=True),
)
async def write(...): ...
```

**Router 整合：**
- process() 呼叫工具前檢查 policy
- 需要 confirm 的工具：先回傳審批請求，LLM 等待結果
- Rate limit / timeout 超標：自動封鎖該工具該輪

---

### Phase 1a — MCP 整合（Priority: 高）

**為什麼要接 MCP：**
- OpenClaw 已經證明了 MCP 是工具生態擴充的最佳路徑
- 不用自己寫每個第三方工具，只要接 MCP server 就好
- 瞬間擴充工具數量：檔案操作、資料庫查詢、Git 操作、...

**Haven 實作方式：**

```
kid/tools/
├── __init__.py
├── cmd.py / write.py / read.py / search.py  ← 現有內建工具
├── policy.py / categories.py                 ← Phase 0
├── mcp/                                      ← 新增
│   ├── __init__.py
│   ├── client.py             # MCP client (stdio / SSE)
│   ├── discovery.py          # 動態發現工具定義
│   └── registry.py           # MCP 工具 ↔ ToolRegistry 轉接層
```

**設計概念：**

```python
class MCPClient:
    """連接外部 MCP server，取得工具列表並橋接到 ToolRegistry。"""
    async def discover_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, args: dict) -> str: ...


class MCPBridge:
    """MCP 工具註冊到 ToolRegistry 的轉接層。
    所有 MCP 工具統一加前綴 mcp__，避免命名衝突。
    """
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    async def attach(self, server_config: dict):
        """從 MCP server 動態發現工具，註冊到 ToolRegistry。"""
        client = MCPClient(server_config)
        tools = await client.discover_tools()
        for t in tools:
            t.name = f"mcp__{t.name}"  # 前綴避免衝突
            t.category = ToolCategory.EXTERNAL
            t.policy = ToolPolicy(require_confirm=True)  # MCP 預設需審批
            self._registry.add(t)
```

**MCP 設定範例（config.yaml）：**

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@anthropic/mcp-filesystem", "/mnt/z"]
  - name: github
    transport: sse
    url: http://localhost:8765/mcp
    # 所有 MCP 工具預設 require_confirm
```

---

### Phase 1b — 工具分類路由（Priority: 中）

Router 根據工具類別自動選擇提供者：
- WEB 類別 → 走 Tavily（當前已有）
- AI 類別 → 走 OpenAI-compatible 模型（DeepSeek 有 vision 就要用）
- FILES / SYSTEM → 走 inline execution（不需 LLM 呼叫）

同時引入 rate limit + timeout 政策：
- cmd: 30s timeout, 每 10s 1 次
- search: 15s timeout, 每 5s 1 次
- write: 10s timeout, 每 2s 1 次

---

### Phase 2 — 持久化記憶系統（Priority: 高，Phase 1 穩定後）

Hermes 的記憶系統比 OpenClaw 更接近人類的方式：不是每次 session 都 fresh，而是累積、壓縮、提煉。

**Haven 現狀：**
`soul/memory.py` 只有基本的 JSON 檔案 session 儲存（保留最近 50 則訊息）。

**目標改造：**

```
kid/soul/
├── memory/
│   ├── __init__.py          # 統一入口
│   ├── session_store.py     # 現有的 session JSON 儲存（保留）
│   ├── long_term.py         # 新增：長期記憶儲存
│   ├── summarizer.py        # 新增：對話摘要壓縮
│   └── index.py             # 新增：全文 / 語義搜尋
```

**長期記憶的資料結構概念：**

```python
class LongTermMemory(BaseModel):
    entries: list[MemoryEntry]

class MemoryEntry(BaseModel):
    id: str                    # UUID
    type: Literal["fact", "preference", "skill", "session_summary"]
    content: str               # 壓縮後的內容
    tags: list[str]            # 分類標籤
    created_at: datetime
    access_count: int          # 被 recall 的次數，用於重要性排序
    last_accessed: datetime
```

**運作流程：**

```
每次對話結束時 →
  1. session_store.py 儲存原始對話
  2. summarizer.py  壓縮成摘要 + 提取關鍵事實
  3. long_term.py   將摘要寫入長期記憶儲存
  4. 下一個 session 啟動時，載入相關長期記憶到 context

關鍵設計：原始對話保留在 session store（用於調閱），
          摘要進入 long term（用於 recall），兩層分離。
```

**搜尋方式（漸進實作）：**
1. 第一版：全文關鍵字搜尋（Python built-in，零依賴）
2. 第二版：向量語義搜尋（ollama embedding，需 GMK 跑得動才啟用）

---

### Phase 3 — 自我改進 / 自動寫 Skill（Priority: 中，Phase 2 穩定後）

這是 Hermes 最亮眼的功能，但也是最有風險的部分。Haven 的版本應該**保守得多**。

**核心概念：**

```
當 KID 發現自己重複做同一件事 →
  自動產生一段「技能記憶」儲存起來 →
  下次遇到類似情境時自動套用 →
  如果套用結果不好，自動修正
```

**Haven 實作方式（非 Hermes 的直接複製）：**

```
kid/learning/
├── __init__.py
├── skill_factory.py    # 根據經驗產生 skill 定義
├── skill_refiner.py    # 根據使用結果自動調整
└── skill_store.py      # 已學習的技能儲存
```

**可學的 / 不可學的範圍：**

| 可自動學習 ✅ | 不可自動學習 ❌ |
|-------------|---------------|
| 檔案讀寫模式 | 任何涉及金錢的操作 |
| 工具呼叫參數偏好 | 密碼 / API key |
| 報告格式偏好 | 系統設定變更 |
| 常用指令縮寫 | 外部帳號登入 |
| 程式碼風格偏好 | 刪除檔案 |

**安全邊界：**
- 自動產生的 skill 預設為 **draft 模式**（不會自動載入）
- 需經過 Cris 審批後才能升為 **active**
- 每個自動 skill 都有版本號和變更紀錄，可回滾

---

### Phase 4 — 子任務委派（Priority: 低）

Router 內支援 spawn child session，類似 OpenClaw 的 sessions_spawn：

```python
class Router:
    async def spawn_child(self, task: str, model_override: str | None = None):
        """建立子 Router 實例，獨立執行任務。
        結果以 tool result 方式回傳。
        """
        ...
```

**限制：**
- 最多 3 層巢狀
- 每個 child 有限 timeout (60s)
- Child 不能 spawn 更多 child（防止暴走）

---

### Phase 5 — 全部融合到現有架構

**重點：不改動現有核心模組（core/router.py、core/tool_registry.py），透過組合擴充。**

```
kid/
├── core/                     ← 不動核心（穩定第一）
│   ├── router.py             ← 微調：掛載 policy/MCP/child
│   ├── tool_registry.py      ← 小改：支援 category + policy
│   └── provider.py
├── tools/                    ← 擴充
│   ├── __init__.py
│   ├── cmd.py / read.py / write.py / search.py
│   ├── policy.py             ← Phase 0
│   ├── categories.py         ← Phase 0
│   └── mcp/                  ← Phase 1a
│       ├── client.py
│       ├── discovery.py
│       └── registry.py
├── soul/                     ← 擴充（Phase 2）
│   ├── __init__.py
│   ├── identity.py
│   └── memory/
│       ├── __init__.py
│       ├── session_store.py     ← 現有，保留
│       ├── long_term.py         ← 新增
│       ├── summarizer.py        ← 新增
│       └── index.py             ← 新增
├── learning/                 ← 新增（Phase 3）
│   ├── __init__.py
│   ├── skill_factory.py
│   ├── skill_refiner.py
│   └── skill_store.py
├── transport/                ← 不動
└── main.py                   ← 微調（啟動時掛載 MCP、載入記憶）
```

**不變的改造原則：**
1. **Interface over Implementation** — 只依賴抽象介面
2. **Opt-in** — 所有新功能預設關閉，Cris 手動啟用
3. **Graceful degradation** — 任何元件載入失敗，fallback 到基礎模式

---

## 三、風險評估

| 風險 | 程度 | 因應 |
|------|------|------|
| 記憶膨脹導致 context 塞爆 | 中 | 重要性分級 + 只載入 top-N |
| 自動 skill 產生錯誤行為 | 高 | Draft mode + Cris 審批閘門 |
| 額外程式碼增加維護成本 | 中 | Phase 分階段，MVP 後才做 |
| 向量搜尋依賴 ollama | 低 | 第一版只用全文搜尋 |

---

## 四、實作時程建議

```
Phase 0 — Tool Policy Layer           → MVP 之後立刻做
  - ToolCategory 定義
  - @tool decorator 加入 category + policy
  - Router 整合政策檢查
  - require_confirm 閘門
  - rate limit / timeout

Phase 1a — MCP 整合                   → Phase 0 穩定後
  - MCP client (stdio / SSE)
  - 動態發現 + 橋接 ToolRegistry
  - 配置驅動的 server 清單
  - 預設 require_confirm 安全策略

Phase 1b — 工具分類路由               → Phase 0 穩定後
  - Router 依類別自動選提供者
  - 分類別 rate limit / timeout

Phase 2a — long_term.py 基礎版         → Phase 1a 穩定後
  - 純 JSON 儲存 + 全文搜尋
  - 對話結束時自動摘要儲存
  - 啟動時載入相關記憶
  - 開發的 tool: soul/memory_search

Phase 2b — 向量搜尋                   → Phase 2a 穩定後
  - ollama embedding 整合
  - 語義相似度 recall

Phase 3a — 自動 skill draft           → Phase 2 穩定後
  - 監測重複行為模式
  - 產生 draft skill
  - Cris 審批流程

Phase 3b — 自動 skill refine          → Phase 3a 成熟後
  - 追蹤使用成效
  - 自動調整

Phase 4 — 子任務委派                   → 最後
  - Router.spawn_child()
  - 3 層巢狀上限
  - 60s timeout
```

---

## 五、討論大綱

### 優先事項

1. **Phase 0 — 工具治理層**（這波 MVP 後先做）
   - 哪些工具需要 require_confirm？（cmd / write 應該要）
   - 分類怎麼切？（FILES / SYSTEM / WEB / AI / MEMORY / COMMUNICATION）
   - @tool decorator 要改多少？要不要改 signature？

2. **Phase 1a — MCP 整合**（Phase 0 後）
   - 要不要先支援 stdio 還是 SSE？還是兩個都做？
   - 第一個接的 MCP server 是什麼？（filesystem？git？）

3. **持久化記憶**（Phase 1a 後）
   - 要存什麼？（對話摘要？提取的事實？使用者偏好？）
   - 多久壓縮一次？（每次？每 N 輪？）
   - Recall 多少？（最近 10 條？重要性 top-5？）

4. **自我學習**（最晚）
   - 安全邊界在哪？（哪些行為可學？哪些絕對不行？）
   - Draft → Active 的審批流程？（手動確認？還是設一個觀察期？）

5. **Haven MVP 定義**
   - python main.py 能順跑對話 + 基本工具？
   - 要包含 transport/Terminal 就夠還是要全平台？

---

> 這份計劃書記錄了 Haven 借鑑 Hermes 與 OpenClaw 的設計理念，但保留了 Haven 自己的風格和節奏。
> 工具治理（Phase 0）是先決條件，安全第一。MCP（Phase 1a）是生態擴充的捷徑，比重新造輪有效率太多。
> 記憶（Phase 2）和自我學習（Phase 3）是長期靈魂，不急。
> 節奏：先穩，再快，再聰明。 💪
