# Haven 改造路線圖：從 CC 設計逐步遷移

> 將 Claude Code 的核心設計模式系統性地融入 Haven
> 確保每一步系統都是可運行的，具備回滾能力
> 日期：2026-06-08

---

## 前提原則

### 不中斷原則
每一步完成後，Haven 的既有功能（mail.py、scan.py、sync、soul
檔案）必須完全正常運作。新功能以平行方式加入，不修改既有
工具程式。

### 回滾協定
每階段完成後建立 checkpoint。回滾 = 還原到前一個 checkpoint。
checkpoint 包含：
- git commit（如果已有版控）或 tar.gz 備份
- 測試清單（哪些通過、哪些失敗）
- 已知問題清單

### 測試門檻
每階段必須通過以下測試才能繼續：
1. 既有工具正常運作
2. 新功能基本可用
3. 無記憶體洩漏（free -m 比對前後差異 < 5%）

---

## Phase 0：地基建立（第 1-3 天）

### 0.1 目錄結構標準化

建立 Haven Agent 的目錄骨架，不影響既有檔案：

```
/mnt/z/Haven/
├── .env                    # 既有，不動
├── sync_log.txt            # 既有，不動
├── mail.py                 # 既有，不動
├── scan.py                 # 既有，不動
├── Soul/                   # 既有，不動
│
├── agent/                  # 🆕 Haven Agent 核心
│   ├── core/               #   核心迴圈
│   ├── permissions/        #   權限系統
│   ├── tools/              #   工具實作
│   ├── compaction/         #   context 壓縮
│   ├── memory/             #   記憶系統
│   └── avatar/             #   系統狀態化身
│
├── lib/                    # 🆕 共用函式庫
│   ├── logger.py
│   ├── config.py
│   └── circuit_breaker.py
│
└── tests/                  # 🆕 測試
    ├── test_core.py
    └── test_circuit_breaker.py
```

**測試：** 目錄存在，既有檔案不受影響

### 0.2 Circuit Breaker 共用模組

第一個實際程式碼。CC 的教訓：**第一天就要有 circuit breaker**。

```python
# lib/circuit_breaker.py

class CircuitBreaker:
    """失敗次數追蹤器，達到上限後停止重試。

    對應 CC autocompact 的 MAX_CONSECUTIVE_FAILURES = 3。
    但比 CC 更安全：從第一天就部署，不等 BigQuery 發現問題。
    """

    def __init__(self, max_failures=3, name="unnamed"):
        self.max_failures = max_failures
        self.name = name
        self.consecutive_failures = 0
        self.total_failures = 0
        self.last_failure_time = None

    def record_failure(self):
        self.consecutive_failures += 1
        self.total_failures += 1
        from time import time
        self.last_failure_time = time()

    def record_success(self):
        self.consecutive_failures = 0

    def is_open(self):
        return self.consecutive_failures >= self.max_failures

    def reset(self):
        self.consecutive_failures = 0
        self.total_failures = 0
```

**測試：**
- 連續失敗 3 次後 circuit 開啟
- 成功後重置
- 日誌記錄每次觸發
- 可匯入 mail.py 和 scan.py 使用

**回滾：** 刪除 agent/ 和 lib/ 目錄即可

---

## Phase 1：核心迴圈（第 4-7 天）

### 1.1 Agent Core Loop（async generator 模式）

Haven 的核心迴圈。參照 CC 的 async generator 模式：

```python
# agent/core/loop.py

class AgentLoop:
    """Haven 的 agentic loop，使用 generator 模式。

    對應 CC query.ts 的 async function* queryLoop。
    每個 yield 是一個 Continue Site，支援暫停 / 恢復。
    """

    def __init__(self, config):
        self.config = config
        self.state = {}
        self.circuit_breaker = CircuitBreaker(name="core-loop")
        self.turn_count = 0

    def turn(self, message):
        """單輪迭代：壓縮 → 模型呼叫 → 權限檢查 → 工具執行 → 結果處理"""
        yield 'compacting', self._compact()
        yield 'thinking', self._call_model(message)
        yield 'checking', self._check_permissions()
        yield 'executing', self._execute_tool()
        yield 'processing', self._process_result()

    def _compact(self): pass        # 第 2 階段實作
    def _call_model(self, msg):     # 包裝 LLM API 呼叫
    def _check_permissions(self):   # 第 3 階段實作
    def _execute_tool(self): pass
    def _process_result(self): pass
```

**測試：**
- 建立簡單迴圈，接受文字輸入並回應
- 不使用 LLM API（用 mock）
- 驗證 generator 可暫停和恢復
- 驗證 circuit breaker 正確運作

**不修改既有檔案：** mail.py、scan.py 完全不用碰

### 1.2 整合現有工具

將 mail.py 和 scan.py 包裝成 agent 可呼叫的工具：

```python
# agent/tools/mail_tool.py

from core.tool_base import Tool

class MailTool(Tool):
    name = "send_email"
    readOnly = False
    destructive = False

    def execute(self, to, subject, body):
        # 呼叫既有的 mail.py 邏輯
        from mail import send_email
        return send_email(to, subject, body)
```

**測試：**
- Agent 可以呼叫 send_email tool
- Agent 可以呼叫 scan tool
- 既有 mail.py CLI 模式仍然可用

**回滾：** 還原 agent/ 目錄到 Phase 0 的 checkpoint

---

## Phase 2：安全系統（第 8-11 天）

### 2.1 Permission Framework

CC 的 default-deny + 拒絕追蹤：

```python
# agent/permissions/manager.py

class PermissionManager:
    """三層權限檢查，對應 CC 的規則層 + hook 層 + degraded mode。"""

    def __init__(self):
        self.rules = {}        # alwaysAllow / alwaysDeny
        self.hooks = []        # PreToolUse hooks
        self.denial_tracker = DenialTracker()  # 46 行版

    def check(self, tool, context):
        # 1. 規則層（最快）
        if tool.name in self.rules:
            return self.rules[tool.name].action

        # 2. Hook 層（可程式化）
        for hook in self.hooks:
            result = hook(tool, context)
            if result is not None:
                return result

        # 3. 預設拒絕（default-deny）
        return 'deny' if not tool.readOnly else 'allow'

class DenialTracker:
    """對應 CC denialTracking.ts，46 行的設計。

    連續 3 次或累計 20 次拒絕 → 降級手動模式。
    """

    def __init__(self):
        self.consecutive = 0
        self.total = 0

    def record_denial(self):
        self.consecutive += 1
        self.total += 1

    def record_approval(self):
        self.consecutive = 0

    def should_degrade(self):
        return self.consecutive >= 3 or self.total >= 20
```

**測試：**
- default-deny：未註冊的工具預設被拒絕
- 拒絕追蹤 3 次後降級
- Hook 可以覆蓋規則
- 既有工具不受影響（它們不走 agent 路徑）

---

## Phase 3：效能系統（第 12-16 天）

### 3.1 Compaction Pipeline

三級管道（簡化版 CC 五層）：

```python
# agent/compaction/pipeline.py

class CompactionPipeline:
    """三級 context 壓縮，由便宜到昂貴。

    Level 1: Tool Result Budget — 截斷超大輸出
    Level 2: Microcompact       — 選擇性清理
    Level 3: Summary            — LLM 總結（最貴，最後才用）
    """

    def compact(self, messages, context):
        # Level 1: 截斷超大工具輸出
        messages = self._apply_tool_budget(messages)

        # Level 2: 清理舊工具結果
        messages = self._microcompact(messages)

        # Level 3: 如果仍然超過門檻，總結（最貴）
        if self._estimate_tokens(messages) > self.threshold:
            messages = self._summarize(messages)

        return messages
```

**關鍵設計（取自 CC）：** 層 2 執行後如果 token 已降至門檻以下，層 3 就不觸發。

**測試：**
- 1 萬 token 的對話可被壓縮至 5 千以下
- 層 3（LLM 總結）只在必要時才呼叫
- 既有工具不受影響

### 3.2 Circuit Breaker 整合

將 Phase 0 的 circuit breaker 接入 compaction pipeline：
- 壓縮失敗超過 3 次 → 停止壓縮，記錄 crash log
- 對應 CC autocompact 的 MAX_CONSECUTIVE_FAILURES

---

## Phase 4：進階功能（第 17-23 天）

### 4.1 ToolSearch（延遲工具載入）

對應 CC 的 ToolSearch pattern：

```python
# agent/tools/search.py

class ToolSearch:
    """延遲工具載入。工具標記 deferred=True 後預設不可見。
    Agent 需要時呼叫 ToolSearch("關鍵字") 按需載入。

    對應 CC 的 defer_loading + ToolSearch meta-tool。
    """

    def search(self, query):
        matches = self._fuzzy_match(query)
        for tool in matches:
            self._inject_schema(tool)
        return matches
```

**測試：**
- 註冊 50 個工具，預設只載入 10 個核心工具
- Agent 搜尋後正確載入匹配工具
- 不浪費預設 token

### 4.2 Verification Agent

CC 最被低估的設計：

```python
# agent/core/verification.py

class VerificationAgent:
    """不信任自己的測試 agent。

    生成任何程式碼後，由這個 agent 獨立驗證。
    其 system prompt 包含合理化藉口清單。"""

    SYSTEM_PROMPT = """
你會想跳過檢查。以下是你會找的藉口——認出它們，然後做相反的事：

- '程式碼看起來是對的' → 讀不等於驗證，跑一次
- '實現者的測試已經過了' → 實現者是 LLM，獨立驗證
- '大概沒問題' → 大概不等於已驗證
- '讓我把伺服器跑起來' → 不，跑起來然後打端點
"""
```

---

## Phase 5：長期（第 24+ 天）

### 5.1 KAIROS 風格記憶系統

CC KAIROS 的三層閘門 + lock 設計：

```python
# agent/memory/kairos.py

class MemoryConsolidator:
    """KAIROS 風格記憶整合。

    三層閘門：
    1. 時間：離上次合併 >= 24 小時
    2. Session 數：累積 >= 5 個 session
    3. 檔案 advisory lock

    Lock 檔案 mtime = lastConsolidatedAt
    失敗可 rollback mtime 恢復前狀態。
    """
```

### 5.2 系統狀態化身

在獨立目錄開發，不影響核心：

```
agent/avatar/
├── avatar.py       # 化身核心邏輯
├── sprites.py      # ASCII 精靈表
└── stats.py        # 狀態計算（從系統讀取指標）
```

---

## 完整路線圖一覽

```
第 1-3 天  [Phase 0] 地基：目錄 + circuit breaker
第 4-7 天  [Phase 1] 核心：async generator loop + 工具整合
第 8-11 天 [Phase 2] 安全：權限框架 + 拒絕追蹤
第 12-16 天 [Phase 3] 效能：三級 compaction + CB 整合
第 17-23 天 [Phase 4] 進階：ToolSearch + Verification Agent
第 24+ 天   [Phase 5] 長期：KAIROS 記憶 + 系統化身
```

### 安全退出點

每個 phase 完成後都是一個穩定版本：
- Phase 0 完成 = 有 circuit breaker 可用的基礎庫
- Phase 1 完成 = 最小可行 agent（MVP）
- Phase 2 完成 = 安全的 agent
- Phase 3 完成 = 長對話可靠的 agent
- Phase 4 完成 = 接近 CC 水準
- Phase 5 完成 = Haven 特色功能

你隨時可以在任何 phase 後喊停，系統都是可運行的。

---

## 何時開始？

如果你想開始，最快的起點是 Phase 0 的目錄結構 + circuit breaker。
我可以今天就把這兩個寫出來，然後你驗證沒問題後，我們再繼續 Phase 1。

要不要先從 Phase 0 開始？
