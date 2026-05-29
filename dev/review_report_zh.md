# Haven 專案 — 工程審查報告

**日期：** 2026-05-29  
**審查者：** KID（子代理）  
**範圍：** 完整架構審查、開發進度評估、CONVENTIONS_EN.md 合規審計

---

## 章節 A：架構審查

### A1. 當前架構 — 表現良好的部分

**1. 乾淨的分層結構。** `kid/` 的目錄層級（core → tools → soul → transport → main）遵循合理的關注點分離。新開發者可以在幾分鐘內理解系統的整體輪廓。

**2. Router 的依賴注入。** `Router.__init__` 將 `ToolRegistry` 和 `providers` 作為建構參數接收——沒有全域變數，沒有寫死的單例模式。這在設計上就是可測試的。

```python
# ./kid/core/router.py:46-50
def __init__(
    self,
    tool_registry: ToolRegistry,
    providers: list[tuple[BaseProvider, str | None]] | BaseProvider,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> None:
```

**3. 提供者備援鏈。** Router 支援（provider, model_override）元組列表，在失敗時會依序嘗試。這實現了優雅的降級，沒有 messy 的 if/else 分支。

**4. OpenAI 相容的 tool calling（非正規表達式）。** build_prototype.md 對原生 tool calling 的規格被忠實實現了。`ToolRegistry.get_openai_tools()` 回傳正確的 `{"type": "function", "function": {...}}` 字典。

**5. `@tool` 裝飾器。** 靈活——可以裸用或帶參數覆寫。透過 `functools.wraps` 保留函式簽名。支援附加到特定註冊器或使用模組層級預設值。

**6. 傳輸層相互隔離。** 每個傳輸層（terminal、Discord、Telegram）都是一個自包含的檔案，只有一個進入點函式。新增傳輸層（如 Slack、WhatsApp）遵循相同模式。

**7. 全面正確的非同步化。** 所有 I/O 透過 `asyncio` + `httpx` 實現非同步。熱路徑中沒有阻塞呼叫。Terminal 將 `input()` 包在 `run_in_executor` 中以避免阻塞事件迴圈。

**8. 工具的路徑安全性。** `cmd.py` 拒絕危險指令和 Shell 特殊字元。`read.py` 和 `write.py` 強制 `/mnt/z/` 前綴。`cmd.py` 還能將 Windows 風格路徑翻譯為 Linux 掛載路徑——周到的 WSL2 相容性。

---

### A2. Build_prototype.md 與實際實現的差距

| 規格 | 狀態 | 細節 |
|---|---|---|
| `soul/memory.py` — JSON session 持久化 | **缺失** | Router 只有 `_history` 記憶體內字典。無檔案備份持久化。 |
| Web search 工具 | **缺失** | 未實作搜尋/索引工具。 |
| `tests/` 目錄 | **缺失** | 專案中完全沒有任何測試檔案。 |
| Pydantic v2 模型 | **未使用** | 所有資料交換使用 raw dict（`list[dict[str, Any]]`、`dict[str, Any]`）。 |
| `tools/write.py` | 已有 | 可運作，但缺少 `.env`/identity 檔案的覆蓋保護邏輯（規格中有提及）。 |
| `transport/discord_bot.py` + `telegram_bot.py` | **額外增加** | 超出原始規格（原始只指定了 terminal）。 |
| 錯誤處理符合規格 | 90% | 工具執行錯誤被捕獲並轉發。Provider 錯誤透過自訂例外處理。缺少領域例外。 |

---

### A3. CONVENTIONS_EN.md 合規 — 違規列表

#### 🔴 鐵律一：單一職責原則（SRP）
**每個檔案最多 200 行。** 違規：

| 檔案 | 行數 | 問題 |
|---|---|---|
| `core/provider.py` | 258 | 2 個類別（DeepSeekProvider + OpenRouterProvider）+ BaseProvider + ProviderError |
| `core/router.py` | 207 | Router 類別 + `_clean` 函式 + 模組層級常數 |
| `core/tool_registry.py` | 255 | ToolSpec + ToolRegistry + 模組層級預設註冊器 + parameter() + @tool + collect_tools |

**後果：** 三個核心檔案都違反 SRP。根據 CONVENTIONS_EN.md，這三支檔案在進一步開發前都必須拆分。

#### 🔴 鐵律三：測試驅動開發（TDD-Lite）
**「沒有關聯測試定義的生產程式碼禁止產生。」**

- 找到零個測試檔案。
- 沒有 `tests/` 目錄。
- 當前狀態下無法進行 RED/GREEN 循環。
- 每一支生產檔案都是在沒有測試的情況下撰寫的。

#### 🔴 第 3.1 節 — Pydantic v2 要求
**「禁止使用 Dict 結構進行核心資料交換。使用 Pydantic v2 進行執行時期驗證。」**

- `Router._build_messages` 回傳 `list[dict[str, Any]]` — raw dict。
- `BaseProvider.chat_completion` 回傳 `dict[str, Any]` — raw dict。
- `ToolSpec.parameters` 是 `dict` 型別——沒有 BaseModel。
- `tool_registry.execute` 回傳 `dict`——沒有 BaseModel。
- 整個程式碼庫中有零個 Pydantic 模型。

#### 🔴 第 3.2 節 — 每個領域的自訂例外
**「每個領域模組必須有自己的自訂例外。」**

- `provider.py` 有 `ProviderError` ✓
- `tool_registry.py` 沒有自訂例外
- `router.py` 沒有自訂例外
- `commands.py`、`read.py`、`write.py` 沒有自訂例外
- `transport/*` 模組沒有自訂例外

#### 🔴 第 3.3 節 — 純無狀態設計
**「所有外部依賴項透過建構函式注入。全域變數嚴格禁止。」**

- `telegram_bot.py` 使用 `global _router`（第 31–32 行）而非建構函式注入。`_router = Router | None` 是一個模組層級的全域變數，處理器會讀取它。

#### 🟡 第 3.2 節 — 裸 except 處理
- `provider.py` — `__init__` 和 `chat_completion` 中的 `except Exception as exc` 有良好型別限定（httpx 特定），可接受。
- `tool_registry.py` — `execute()`（第 128 行）中的 `except Exception` 雖然寬泛，但在工具分發邊界上是防禦性的——邊緣可接受。
- `router.py` — provider 備援迴圈中的 `except Exception`（第 99 行）——作為系統邊界可接受。

#### 🟡 開發節奏合規

沒有一段程式碼是依照 CONVENTIONS_EN.md 的四步循環撰寫的：
- 步驟 1（架構定錨）沒有卡點審查。
- 步驟 2（測試先行）從未執行。
- 步驟 3–4 在沒有步驟 1–2 的情況下完成。

---

## 章節 B：開發進度評估

### 🟢 綠色——已完成且可運作

| 元件 | 檔案 | 狀態 |
|---|---|---|
| LLM Provider（DeepSeek） | `core/provider.py` | 可運作。可連接、發送訊息、接收 tool calls。對 HTTP/逾時/JSON 問題有錯誤邊界。 |
| LLM Provider（OpenRouter） | `core/provider.py` | 可運作。相同介面，備援路由已就緒。 |
| ReAct 迴圈 Router | `core/router.py` | 可運作。非遞迴 while 迴圈、max_turns、provider 備援。 |
| Tool Registry | `core/tool_registry.py` | 可運作。註冊、OpenAI schema 產生、分發、`@tool` 裝飾器、`parameter()` 輔助函式。 |
| execute_command 工具 | `tools/cmd.py` | 可運作。安全檢查、特殊字元拒絕、路徑翻譯、30 秒逾時。 |
| read_file 工具 | `tools/read.py` | 可運作。路徑驗證、二進位檔偵測、前綴檢查。 |
| write_file 工具 | `tools/write.py` | 可運作。（讀取輸出被截斷；透過檔案列表確認存在。） |
| Terminal 傳輸層 | `transport/terminal.py` | 可運作。可優雅退出的非同步 REPL。 |
| Discord 傳輸層 | `transport/discord_bot.py` | 已實作。需 DISCORD_TOKEN 才能啟動。 |
| Telegram 傳輸層 | `transport/telegram_bot.py` | 已實作。需 TELEGRAM_TOKEN 才能啟動。 |
| 身份/系統提示 | `soul/identity.py` | 可運作。從 `/mnt/z/Core/identity.md` 載入。 |
| 進入點 | `main.py` | 可運作。乾淨啟動、連接所有元件、並行執行傳輸層。 |

### 🟡 黃色——部分完成

| 元件 | 問題 |
|---|---|
| 錯誤處理覆蓋率 | ProviderError 存在，但 registry、router、tools、transports 沒有領域特定例外。 |
| Provider 模型 | 沒有 Pydantic 模型。到處使用 raw dict。可運作但嚴格違反 CONVENTIONS_EN.md。 |
| Discord 傳輸層 | 已建置但未測試（token 可能缺失）。token 不存在時 `run_discord` 回傳一個 no-op future。 |
| Telegram 傳輸層 | 已建置但使用 `global _router`（反模式）。main.py 中沒有優雅關機邏輯。 |

### 🔴 紅色——缺失項目

| 元件 | 優先級 | 影響 |
|---|---|---|
| **測試**（`tests/`） | 關鍵 | 沒有測試就無法進行 TDD-Lite。零測試覆蓋率意味著回歸問題不可見。 |
| **soul/memory.py** | 高 | Session 歷史只在記憶體內。重新啟動應用程式→失去所有對話上下文。 |
| **Web search 工具** | 中 | build_prototype.md 未指定 `web_search`/`index` 工具，但對代理能力有用。 |
| **Pydantic 模型** | 高 | 所有資料交換違反 CONVENTIONS_EN.md 第 3.1 節。每個 dict 都應該是 BaseModel。 |
| **檔案拆分（SRP）** | 高 | provider.py（258）、router.py（207）、tool_registry.py（255）必須拆分。 |
| **自訂領域例外** | 中 | 只有 ProviderError 存在。需要 RouterException、RegistryException、ToolException、TransportException。 |
| **write.py 覆蓋保護** | 低 | 規格提到保護 `.env`/identity 檔案不被覆蓋。尚未實作。 |
| **CI / 測試執行器配置** | 中 | 沒有 pytest 配置、沒有 CI 管線、沒有測試發現設定。 |

---

## 章節 C：下一步建議

### C1. 立即優先事項（按順序）

#### 優先事項 1：重構以修復 SRP 違規

**目標：** 拆分三個過大的檔案以符合 200 行限制。

| 檔案 | 建議拆分 | 拆分後行數 |
|---|---|---|
| `core/provider.py`（258） | → `core/base_provider.py`（BaseProvider + ProviderError，~50行）、`core/deepseek_provider.py`（~130行）、`core/openrouter_provider.py`（~80行）、`core/provider.py`（重新匯出/別名） | 全部 ≤ 130 |
| `core/router.py`（207） | → `core/router.py`（僅 Router 類別，~150行）、`core/_clean.py` 或內聯輔助函式 | ≤ 150 |
| `core/tool_registry.py`（255） | → `core/tool_spec.py`（ToolSpec + parameter，~50行）、`core/tool_registry.py`（ToolRegistry + default_registry，~100行）、`core/tool_decorator.py`（@tool + collect_tools，~80行） | 全部 ≤ 100 |

**滿足的公約條文：** 鐵律一（SRP）  
**預估工作量：** 1 個 session（~100 行重構）

---

#### 優先事項 2：加入 Pydantic v2 模型

**目標：** 用型別化的 `BaseModel` 類別取代所有 raw dict。

建立 `core/models.py`：
```python
from pydantic import BaseModel
from typing import Optional

class ProviderResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    reasoning_content: Optional[str] = None
```

然後更新簽名：
- `BaseProvider.chat_completion()` 回傳 `ProviderResponse`
- `Router.process()` 內部使用 `ProviderResponse`
- `ToolSpec.parameters` 保持為 dict（它是 JSON Schema，不是業務資料）

**滿足的公約條文：** 第 3.1 節（Pydantic v2）  
**預估工作量：** 1 個 session（~80 行新模組、~30 行重構）

---

#### 優先事項 3：建立領域特定例外

**目標：** 每個模組獲得自己的例外層級。

```python
# core/exceptions.py
class HavenError(Exception): ...
class ProviderError(HavenError): ...
class RouterError(HavenError): ...
class RegistryError(HavenError): ...
class ToolError(HavenError): ...
class TransportError(HavenError): ...
```

或每個模組獨立：
- `core/provider.py` 保留 `ProviderError`
- `core/router.py` 新增 `RouterError`
- `core/tool_registry.py` 新增 `RegistryError`
- `tools/exceptions.py` 新增 `ToolExecutionError`
- `transport/exceptions.py` 新增 `TransportError`

**滿足的公約條文：** 第 3.2 節（領域例外）  
**預估工作量：** ½ 個 session（~50 行新模組）

---

#### 優先事項 4：建構 soul/memory.py（Session 持久化）

**目標：** 根據 `build_prototype.md` 實現 JSON 檔案備份的 session 歷史。

```
soul/memory.py（~60 行）：
  - SessionStore 類別
  - load(session_id) → list[dict]（從 /mnt/z/Haven/dev/kid/sessions/{id}.json 載入）
  - save(session_id, messages)
  - prune() → 保留最近 50 則
```

修改 `Router` 以接受可選的 `SessionStore` 透過 DI 注入。如果提供，則在每次 `process()` 呼叫時刷新歷史。

**滿足的公約條文：** 第 3.3 節（無狀態設計——記憶體模組是唯一的明確例外）  
**預估工作量：** 1 個 session（~60 行新模組）

---

#### 優先事項 5：加入測試基礎設施 + 首批測試

**目標：** 建立 `tests/` 目錄、pytest 配置，為首批元件撰寫 RED/GREEN 測試。

```
tests/
├── conftest.py        # 固定裝置：mock provider、mock registry、test router
├── test_provider.py   # 測試 chat_completion 成功、逾時、HTTP 錯誤、格式錯誤 JSON
├── test_router.py     # 測試基本流程、tool call 流程、max_turns、provider 備援
├── test_tool_registry.py  # 測試註冊、get_openai_tools、execute、未知工具
├── test_cmd.py        # 測試安全檢查、路徑翻譯
└── test_read.py       # 測試路徑驗證、二進位偵測、檔案不存在
```

**滿足的公約條文：** 鐵律三（TDD-Lite）——為所有未來工作啟用 RED/GREEN 循環  
**預估工作量：** 1–2 個 session（~100 行測試）

---

### C2. 建議行動計畫（3–5 個工作 Session）

| Session | 重點 | 變更的檔案 | 滿足的公約條文 |
|---|---|---|---|
| **Session 1** | SRP 拆分 + 領域例外 | 拆分 provider.py（3 檔）、router.py（1 檔）、tool_registry.py（3 檔）。新增 exceptions.py。 | 鐵律一、第 3.2 節 |
| **Session 2** | Pydantic 模型 + memory.py | 新增 `core/models.py`、`soul/memory.py`。更新 Router 以接受 SessionStore DI。 | 第 3.1 節、第 3.3 節 |
| **Session 3** | 測試第一批 | 建立 `tests/` 目錄、`conftest.py`、test_provider.py、test_router.py、test_tool_registry.py | 鐵律三 |
| **Session 4** | 測試第二批 + 工具測試 | test_cmd.py、test_read.py、test_write.py。修復 telegram_bot 全域變數。 | 鐵律三、第 3.3 節 |
| **Session 5**（可選） | Web search 工具 + CI 配置 | 新增 `tools/search.py`（透過 @tool）、pytest 配置、GitHub Actions 或類似方案 | 鐵律二（新功能 = 新模組） |

**順序邏輯：**
1. 先修 SRP——在加入任何東西之前架構必須乾淨。
2. 接著加入 Pydantic + 持久化——這些是憲法要求且阻礙進展的。
3. 結構變更後再寫測試——為即將拆分的程式碼寫測試沒有意義。
4. 其餘清理工作可選——修復 telegram_bot 全域變數、write.py 覆蓋保護。

---

### C3. 風險評估

| 風險 | 可能性 | 影響 | 緩解措施 |
|---|---|---|---|
| 拆分過程中破壞現有功能 | 中 | 高 | 拆分前撰寫整合冒煙測試，每次拆分後執行 |
| 結構變更後才補測試 = 重構沒有紅綠循環 | 低 | 中 | 可接受——憲法允許既有框架重構至多 100 行，不需完整節奏 |
| Discord/Telegram token 可能已變更 | 低 | 低 | 程式碼中已有優雅降級的 no-op 備援 |
| Session 5（web search）可能導致功能蔓延 | 中 | 低 | 鐵律二允許新模組；只要不修改現有可運作程式碼即可 |
| 重構期間可能影響真實使用者 | 低 | 低 | 目前僅 terminal/CLI 使用——無正式流量 |

---

## 總結

Haven 專案有一個紮實、可運作的原型，約 **1323 行**分布在 **14 個檔案**中。架構合理、程式碼可執行、tool-calling 迴圈正確。然而，程式碼庫是在 CONVENTIONS_EN.md 框架之外建置的，導致了三個關鍵的 SRP 違規、零測試、零 Pydantic 模型，以及部分例外覆蓋率。

**達到完全 CONVENTIONS_EN.md 合規所需的預估工作量：** 4–5 個集中 Session。

**任何新功能開發前的阻礙項目：**
1. SRP 檔案拆分（3 個核心檔案）——否則 200 行規則會阻擋所有變更。
2. 測試基礎設施——否則 TDD-Lite 會阻擋所有新程式碼產生。

**建議：** 在加入任何新功能之前，按順序執行 Session 1→4。將 web search 工具（Session 5）視為延伸目標，而非必要條件。
