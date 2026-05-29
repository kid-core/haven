# Haven Core 原型 — 建置規格說明

## 概述

為「Haven」打造一個 Python 原型——輕量、可靠的 AI 輔助核心，使用**原生 OpenAI 相容的 tool calling**（非正規表達式文字解析）。當主要 OpenClaw 代理不可用時，此系統將作為備援／逃生方案。

目錄：`/mnt/z/Haven/dev/kid/`

所有開發作業受 `CONVENTIONS.md` 管轄（三條鐵律、TDD-Lite、3.5 節架構工藝）。

設定完成後，可透過 `./start.sh` 一鍵啟動。

---

## 當前架構

```
kid/
├── core/
│   ├── __init__.py
│   ├── base_provider.py    # 抽象 BaseProvider + ProviderError
│   ├── http_provider.py    # 設定驅動的 HttpProvider（一個類別適用任何 API）
│   ├── router.py           # 狀態機管線（非遞迴 ReAct 迴圈）
│   ├── tool_spec.py        # ToolSpec 資料類別
│   ├── tool_registry.py    # 字典分發模式的 ToolRegistry
│   ├── tool_decorator.py   # @tool 裝飾器 + 預設註冊器
│   ├── models.py           # Pydantic v2 資料模型
│   └── exceptions.py       # 領域例外層級
├── tools/
│   ├── __init__.py         # 註冊所有內建工具
│   ├── cmd.py              # 安全的 Shell 指令執行
│   ├── write.py            # 具路徑驗證的檔案寫入
│   └── read.py             # 檔案讀取
├── soul/
│   ├── __init__.py
│   ├── identity.py         # 系統提示組合、自我認知
│   └── memory.py           # 對話歷史管理（JSON 檔案式）
├── transport/
│   ├── __init__.py
│   ├── terminal.py         # 簡易終端機 REPL
│   ├── discord_bot.py      # Discord @提及和私訊處理
│   └── telegram_bot.py     # Telegram 訊息處理
├── tests/
│   ├── conftest.py         # Pytest 固定裝置（sys.path）
│   └── test_smoke.py       # 結構性煙霧測試
├── start.sh                # 一鍵啟動腳本
└── main.py                 # 含優雅關機的進入點
```

---

## 元件規格

### 1. `core/base_provider.py` — 抽象 LLM 提供者介面

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

### 2. `core/http_provider.py` — 設定驅動 HTTP 提供者

單一類別適用任何 OpenAI 相容 API。所有差異透過建構函式設定傳入：

```python
class HttpProvider(BaseProvider):
    def __init__(self, *, name: str, model: str, base_url: str,
                 api_key_env: str, timeout: float = 120.0,
                 default_temperature: float = 0.3,
                 headers_extra: dict[str, str] | None = None): ...

    async def chat_completion(self, messages, tools=None,
                              temperature=None, max_tokens=None) -> ProviderResponse:
        # 使用衛句型式：HTTP／逾時／解析錯誤時 early raise
        # 回傳 ProviderResponse（Pydantic 模型）
```

使用範例：

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

將原本單一的 tool_registry 拆成三個符合 SRP 的檔案：

**`tool_spec.py`** — ToolSpec 資料類別：
```python
@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[Any]]
```

**`tool_registry.py`** — ToolRegistry（字典分發模式）：
```python
class ToolRegistry:
    def __init__(self): ...
    def add(self, spec: ToolSpec) -> ToolSpec: ...
    def get_openai_tools(self) -> list[dict]: ...
    async def execute(self, tool_call_id, name, arguments) -> dict: ...
    def __contains__(self, name: str) -> bool: ...
    def __len__(self) -> int: ...
    def __iter__(self): ...
```

**`tool_decorator.py`** — @tool 裝飾器 + 預設註冊器：
```python
def tool(_func=None, *, name=None, description=None,
         parameters=None, registry=None) -> Any: ...
def get_default_registry() -> ToolRegistry: ...
```

### 4. `core/router.py` — 狀態機路由器

具備提供者備援鏈的非遞迴 ReAct 迴圈。

```python
class Router:
    def __init__(self, tool_registry: ToolRegistry,
                 providers: list[tuple[BaseProvider, str | None]],
                 system_prompt: str = ...): ...

    async def process(self, user_message: str,
                      session_id: str = "default",
                      max_turns: int = 10) -> str: ...
```

關鍵規則：
- **禁止遞迴。** 使用 `while` 迴圈搭配 `max_turns` 上限。
- **正確的角色順序：** user → assistant (含 tool_calls) → tool → ...
- **工具結果格式為 `{"role": "tool", "tool_call_id": "...", "content": "..."}`**
- **提供者備援：** 主要提供者失敗時，自動嘗試鏈中的下一個。
- **錯誤處理：** 工具呼叫失敗以錯誤訊息作為 tool content 回傳（不要崩潰）。
- **深度上限回傳明確的錯誤訊息，而非切換模式。**

### 5. `core/models.py` — Pydantic v2 資料模型

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

### 6. `core/exceptions.py` — 領域例外

```python
class HavenError(Exception): ...
class ProviderError(HavenError): ...
class RouterError(HavenError): ...
class RegistryError(HavenError): ...
```

### 7. 工具

每個工具是透過 `@tool` 註冊的獨立 Python 檔案：

- **`tools/cmd.py`** — `execute_command(cmd: str)` — 安全 Shell 執行，含特殊字元拒絕、危險指令黑名單、30 秒逾時。
- **`tools/write.py`** — `write_file(path: str, content: str)` — 在 `/mnt/z/` 路徑下寫入檔案，拒絕覆蓋受保護檔案（`.env`、`.key`）。
- **`tools/read.py`** — `read_file(path: str)` — 讀取 `/mnt/z/` 路徑下的檔案，自動偵測二進位檔。

### 8. `soul/identity.py` — 系統提示建構器

載入 `/mnt/z/Core/identity.md` 作為基礎身份。建構含身份、工具使用說明、模式上下文的系統提示。

### 9. `soul/memory.py` — 對話歷史

```python
class SessionStore:
    def __init__(self, session_dir, max_messages=50): ...
    def load(self, session_id) -> list[dict]: ...
    def save(self, session_id, messages) -> None: ...
```

- 每個 session 的 JSON 檔案儲存於 `/mnt/z/Haven/dev/kid/sessions/{session_id}.json`
- 最多保留最近 50 則訊息，儲存時自動修剪

### 10. 傳輸層

三個並行傳輸層，共享同一個 Router 實例（透過建構函式注入）：

- **`transport/terminal.py`** — 簡易 REPL，使用 `Cris>` 提示字。在 thread executor 中執行以避免阻塞事件迴圈。
- **`transport/discord_bot.py`** — 回應 @提及和私訊。需設定 `DISCORD_TOKEN`。
- **`transport/telegram_bot.py`** — 處理文字訊息。使用建構函式注入（無全域變數）。需設定 `TELEGRAM_TOKEN`。

### 11. `main.py` — 進入點

```python
async def main():
    # 1. 註冊訊號處理器（SIGINT/SIGTERM → asyncio.Event）
    # 2. 初始化 ToolRegistry
    # 3. 註冊內建工具（匯入 tools/__init__.py）
    # 4. 初始化提供者（DeepSeek 主要、OpenRouter 備援）
    # 5. 初始化 Router
    # 6. 並行啟動所有傳輸層
    # 7. 等待關機訊號或任一傳輸層結束
    # 8. 優雅關機：停止 Telegram → 取消任務 → 關閉提供者
```

### 12. `start.sh` — 一鍵啟動腳本

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

## 實作備註

- **全面使用 `asyncio`。** 所有 I/O 都應為非同步。
- **使用 `httpx`** 進行非同步 HTTP 呼叫 LLM API。
- **依賴注入** — Router 透過建構子參數接收 ToolRegistry 和 Provider，非寫死。
- **Pydantic v2** 用於所有核心資料交換。跨模組邊界不使用裸 dict。
- **衛句型式（Guard Clauses）** — 錯誤提早捕獲並立即拋出。無巢狀錯誤處理。
- **無全域變數** — Telegram 處理器以實例屬性儲存 router，而非模組層級的 `global`。
- **安全性** — 拒絕路徑遍歷、危險 Shell 指令、寫入受保護檔案。
- **優雅關機** — 訊號處理器、有序清理（Telegram → 任務 → 提供者）。

---

## 測試方式

```bash
# 啟用虛擬環境
source /mnt/z/Core/.venv/bin/activate

# 方式 A：一鍵啟動
cd /mnt/z/Haven/dev && ./kid/start.sh

# 方式 B：手動啟動
cd /mnt/z/Haven/dev && python kid/main.py

# 執行結構性測試
cd /mnt/z/Haven/dev && python -m pytest kid/tests/ -v
```

預期行為：
1. 輸入一段訊息
2. 系統呼叫 LLM、執行工具、回傳回應
3. 輸入 "exit" 或按 Ctrl+C 優雅關機

---

## 環境設定

- API 金鑰從 `/mnt/z/Core/.env` 和 `/root/.openclaw/env` 載入
- DeepSeek：`DEEPSEEK_API_KEY`
- OpenRouter（備援）：`OPENROUTER_API_KEY`
- Discord：`DISCORD_TOKEN`
- Telegram：`TELEGRAM_TOKEN`
- 虛擬環境：`/mnt/z/Core/.venv/`（執行前需啟用）

---

## 管轄文件

- `CONVENTIONS_EN.md` — 架構憲法（三條鐵律、TDD-Lite、第 3.5 節架構工藝）
- `CONVENTIONS.md` — 同上，中文版

所有程式碼必須遵循。違規將觸發 AI 工程師 KID 的警告。
