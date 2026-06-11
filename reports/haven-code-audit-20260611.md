# Haven 程式碼審計報告 — 冗餘 / 重複 / 不和諧

> 審計日期：2026-06-11
> 審計範圍：`/mnt/z/Haven/` 完整程式碼庫
> 審計方式：源碼閱讀 + 目錄結構比對 + 路徑/持久化交叉驗證

---

## 🚨 結構層級 — 最嚴重的冗餘

### 1. 三重 `long_term_memory` 目錄

| 路徑 | 內容 | 狀態 |
|------|------|------|
| `/mnt/z/Haven/long_term_memory/` | tasks.json (404B) + tasks_archive.json (1.4KB) | 殘留，未被任何程式碼使用 |
| `/mnt/z/Haven/dev/long_term_memory/` | tasks.json (2 bytes) + tasks_archive.json (12KB) | 已過時，幾乎空的 |
| `/mnt/z/Haven/dev/kid/long_term_memory/` | memory.json (120KB) + .bak + schedules.json + tasks* | ✅ **實際運作目錄** |

**不一致點：** Router 用相對路徑 `"long_term_memory/tasks.json"`（取決於 CWD），而 Scheduler 用絕對路徑 `/mnt/z/Haven/dev/kid/long_term_memory/schedules.json`。一旦 CWD 變了，Router 會寫到不同的位置。

---

### 2. 測試目錄雙軌制

- **`/mnt/z/Haven/tests/retired/`** — 10 個已退休測試，共 ~14,000 行程式碼
  - `test_phase1.py` ~ test_phase5b.py（舊階段命名，已過時）
  - `test_loop_multi_turn.py`、`test_model_native_tools.py` 等
- **`/mnt/z/Haven/tests/RETIRED.md`** — 明確標示為已棄用
- **`/mnt/z/Haven/tests/__pycache__/`** — 仍留有快取，表示可能無意中被執行過
- **`/mnt/z/Haven/dev/kid/tests/`** — 30+ 個活躍測試（✅ 正確位置）

這些退休測試佔空間、混淆開發者、且 CI 不會執行它們。

---

### 3. 三重任務持久化

三個位置的 `tasks.json` + `tasks_archive.json` 內容不同，代表同一類資料分散在多處：

```
/mnt/z/Haven/long_term_memory/tasks.json           → 404 bytes
/mnt/z/Haven/dev/long_term_memory/tasks.json       → 2 bytes（幾乎空的）
/mnt/z/Haven/dev/kid/long_term_memory/tasks.json   → 404 bytes（跟 root 的相同？不確定哪個是最新的）
/mnt/z/Haven/dev/kid/long_term_memory/memory.json  → 120KB（LongTermMemory 的真正儲存）
```

任務排程器與任務管理器各自用不同的儲存路徑，無法保證資料一致性。

---

### 4. 對話 Session 重複

| 路徑 | 大小 | 狀態 |
|------|------|------|
| `dev/kid/sessions/discord:893743161338396692.json` | 76KB | ✅ 活躍 |
| `dev/kid/sessions_backup/discord:893743161338396692.json` | 110KB | 🗑️ 舊備份，較大（更多歷史） |
| `dev/kid/sessions_backup/discord:1496781295878148106.json` | 33KB | 🗑️ 其他頻道的備份 |
| `dev/kid/sessions_backup/telegram:983821360.json` | 15KB | 🗑️ Telegram 備份 |
| `dev/kid/sessions_backup/terminal.json` | 40KB | 🗑️ 終端機備份 |

`sessions/` 跟 `sessions_backup/` 沒有同步機制。`sessions_backup/` 只會一直增長，不會被清理。

---

### 5. 記憶體系統分裂

| 路徑 | 內容 |
|------|------|
| `/mnt/z/Haven/memory/` | 2026-06-02.md + `logs/` 子目錄 |
| `/mnt/z/Haven/workspace_memory/` | 2026-05-26.md ~ 2026-05-30.md（5 個檔案） |

兩個目錄存放同一類內容（對話記錄/會議記錄），但日期無重疊。說明是**不同時期使用不同的命名慣例**，沒有遷移痕跡。

---

### 6. Soul 資料 VS Soul 程式碼

| 路徑 | 用途 |
|------|------|
| `/mnt/z/Haven/Soul/Chronicle.md` | runtime soul 資料 — KID 編年史 |
| `/mnt/z/Haven/Soul/Memory/session_*.json` | session 歷史（跟 sessions/ 重疊） |
| `/mnt/z/Haven/Soul/latest_summary.txt` | 最新摘要 |
| `/mnt/z/Haven/dev/kid/soul/` | soul 系統的 Python 原始碼 |

資料與程式碼分開是好的設計，但 `Soul/Memory/session_*.json` 跟 `dev/kid/sessions/*.json` 儲存同一類資料，**沒有明確的所有權邊界**。

---

### 7. 文件目錄膨脹

`doc/` 有 4 個子目錄，共 17+ 個檔案：

| 子目錄 | 檔案數 | 問題 |
|--------|--------|------|
| `doc/manual/` | 5 個 | README 有 .md + .txt 兩個版本 |
| `doc/technical/` | 7 個 | 3 張架構圖（2 張 PNG 共 427KB），CONVENTIONS 中英雙語，ENVIRONMENTS 中英雙語 |
| `doc/plans/` | 4 個 | 部分計劃已過時（ai_ea_trading_assistant 跟核心功能無關） |
| `doc/history/` | 5 個 | Sync_Map.md 在根目錄還有另一個副本 |

`.md` + `.txt` 雙格式有 SOP 原因，但總體文件量已偏大。

---

## ⚠️ 程式碼層級冗餘

### 8. `_clean()` 函數重複兩次

`router.py` 和 `background_agent.py` 各自宣告完全相同的 `_clean()` 函數：

```python
_SURROGATE_RE = re.compile(r"[" + "".join(chr(c) for c in range(0xD800, 0xE000)) + "]")
def _clean(text: str | None) -> str:
    if not text:
        return ""
    return _SURROGATE_RE.sub("", text)
```

DRY 違反。應提取到共用工具模組（如 `core/exceptions.py` 或新增 `core/utils.py`）。

---

### 9. 重複的 .env 載入

`.env` 在以下位置被重複載入：

1. `main.py`（3 次：core_env + haven_env + openclaw_env）
2. `discord_bot.py`（同 3 次）
3. `telegram_bot.py`（同 3 次）
4. `http_provider.py`（2 次：openclaw_env + core_env）

總計 **最多 11 次重複載入**。實際上只要載入一次就夠，因為 `load_dotenv()` 不會覆蓋已存在的環境變數，但這仍然是不必要的程式碼執行。

---

### 10. BackgroundAgent 是 Router 的克隆

`background_agent.py`（~304 行）擁有自己完整的 ReAct loop，與 `router.py` 的 `process()` / `_execute_tool()` 重複約 70%：

- 自己的 provider fallback loop
- 自己的工具執行邏輯（含 PolicyBlockedError、timeout 處理）
- 自己的 `_clean()`
- 自己的訊息歷史管理

**建議：** 提取共同 ReAct loop 到基底類別（如 `BaseReActLoop`），Router 和 BackgroundAgent 各自繼承。

---

### 11. MemoryIndex 從未被使用

`dev/kid/soul/memory/index.py` 定義了 `MemoryIndex` 類別（69 行），包裝 `LongTermMemory` 提供更好的全文搜尋。但整個 codebase 中**沒有任何 from/import**。

而 `LongTermMemory.search()` 自己就已經有基本搜尋功能。

---

### 12. `_build_capability_summary()` 每次重算

`router.py` 的 `_build_capability_summary()` 在每次建立新 session 時都重新編譯工具列表和模型列表的字串。這些幾乎不變，可以快取成類別變數。

---

### 13. `paths.py` 定義了不存在的目錄

| `paths.py` 函數 | 傳回路徑 | 實際存在？ |
|---|---|---|
| `config_dir()` | `HAVEN_ROOT/config` | ❌ |
| `data_dir()` | `HAVEN_ROOT/data` | ❌ |
| `ltm_dir()` | `HAVEN_ROOT/data/long_term_memory` | ❌ |
| `session_dir()` | `HAVEN_ROOT/data/sessions` | ❌ |
| `skills_dir()` | `HAVEN_ROOT/data/skills` | ❌ |

真正的持久化資料放在：
- `HAVEN_ROOT/long_term_memory/`
- `HAVEN_ROOT/dev/kid/sessions/`
- `HAVEN_ROOT/dev/kid/long_term_memory/`

**路徑藍圖與現實完全脫節。**

---

### 14. PendingFileStore 可以合併

`core/pending_file.py`（89 行）只是一個 `dict[str, list[PendingFile]]` 的薄包裝。只被 `router.py` 單一處 import。可以整合進 TransportAdapter 或 Router 自身。

---

### 15. Config 不一致的 frozen/property 混合

`HavenConfig` 宣告為 `frozen=True`，但有三個 `@property` 在 runtime 讀 env var：

```python
@dataclass(frozen=True)
class HavenConfig:
    primary_model: str = field(...)    # frozen 模式：建構時決定
    fallback_model: str = field(...)   # frozen 模式
    
    @property
    def allowed_prefix(self) -> str:   # runtime 才讀 env
        return os.getenv(...)
    
    @property
    def discord_token(self) -> str:    # runtime 才讀 env
        return os.getenv(...)
```

要嘛全部 frozen（在建構時讀好所有 env），要嘛全部改用 property。

---

### 16. requirements 版本不一致

| 套件 | `dev/requirements.txt` | `dev/kid/requirements-ci.txt` |
|------|----------------------|------------------------------|
| pytest | `>=8.4` | `>=9.0` |
| ruff | `>=0.11` | `>=0.15` |
| pydantic | `>=2.13` | `>=2.0` |

CI 跟本地開發可能使用不同版本的套件，造成「CI 過本地不過」或反向的問題。

---

## 🔶 設計不和諧

### 17. SkillStore 無法持久化

`skill_store.py` 中 `DEFAULT_SKILL_DIR` 解析到 `/mnt/z/Haven/dev/skills_store/`，但這個目錄**不存在**。每次重啟 Haven，所有學習到的 skill 都會消失。

`paths.py` 定義的 `skills_dir()` → `/mnt/z/Haven/data/skills/` 也一樣不存在。

---

### 18. .env 保留舊 token 名稱

根目錄 `.env`：
```
HAVEN_DISCORD_TOKEN=***    ← 新版（config.py 優先使用）
DISCORD_TOKEN=***          ← 舊版（config.py 用做 fallback）
HAVEN_TELEGRAM_TOKEN=***  ← 新版
TELEGRAM_TOKEN=***        ← 舊版
```

這是遷移過程的正常產物，但值得清理以減少混淆。

---

### 19. 三種行程管理策略

| 機制 | 適用範圍 | 狀態 |
|------|----------|------|
| `haven_tmux.sh` | WSL2 內 tmux 監控 | ✅ 使用中 |
| `haven-discord.service` | Linux systemd service | ✅ 可用 |
| `start_haven.bat` + `stop_haven.bat` | Windows 批次包裝 | ✅ 可用 |
| `Core/watchdog_kid.bat` | Windows 自動重啟 | 存在但屬於 Core 系統 |
| `start_discord.sh` | **指向已不存在的** `haven_discord.py` | ❌ 已過時 |
| `dev/kid/start.sh` | 簡單啟動腳本，跟 haven_start.sh 功能重疊 | ⚠️ 冗餘 |

---

### 20. CI 只覆蓋新測試

`.github/workflows/ci.yml` 的 `working-directory: dev/kid` 只跑 `dev/kid/tests/`。根目錄的舊 `tests/retired/` 不被 CI 檢查，只是佔空間。

---

### 21. 舊報告未清理

`reports/` 包含 7 份文件（~62KB），部分引用已不存在的舊階段命名（Phase 1-5）：

| 檔案 | 問題 |
|------|------|
| `claude-code-design-analysis.md` + `.txt` | 來自 Phase 3 時期的分析 |
| `haven-migration-roadmap.md` + `.txt` | 遷移路線圖，可能已執行完 |
| `p2-next-steps-workflow.md` + `.txt` | Phase 2 工作流程，已過時 |
| `haven-cleanup-plan.md` | 清理計劃，可能已被新的取代 |

---

## ✅ 做得好的設計

為求平衡，值得記錄的優點：

| 元件 | 優點 |
|------|------|
| **HttpProvider** | 單一類別取代了舊的多個 provider（DeepSeek、OpenRouter），DRY 執行良好 |
| **TransportAdapter** | 很好的抽象層，Discord/Telegram/未來 transport 共用管道 |
| **resource_gate.py** | SRP 執行良好，一個類別一個職責 |
| **CircuitBreaker** | 乾淨的狀態機實作（CLOSED→OPEN→HALF_OPEN） |
| **HavenConfig frozen dataclass** | 理念正確，讓設定不可變（雖然部分貫徹不完全） |
| **categories.py** | 清晰的列舉 + 優雅的 `default_policy()` 回退 |
| **CrashJournal** | 專注的 crash 日誌系統 |
| **.github/workflows/ci.yml** | 只在 `dev/kid/` 變更時觸發，有效率的 CI |

---

## 📋 建議優先級

### 🔴 立刻清理（無風險，5 分鐘）

1. 刪除 `/mnt/z/Haven/tests/retired/` + `tests/RETIRED.md` + `tests/__pycache__/`（~14,000 行死程式碼）
2. 刪除 `/mnt/z/Haven/long_term_memory/`（根目錄的 tasks 殘留）
3. 刪除 `/mnt/z/Haven/dev/long_term_memory/`（空的 tasks 殘留）
4. 清空 `sessions_backup/`（手動備份，可以刪）
5. 刪除 `start_discord.sh`（指向不存在的檔案）

### 🟡 短期內（1-2 天，安全但影響較大）

6. 統一 task storage 到一個確定的路徑（用 `paths.py` 為主）
7. 統一 session storage 到 `paths.py` 定義的位置
8. 提取 `_clean()` 到共用工具（`core/utils.py` 或 `exceptions.py`）
9. 清除重複的 .env 載入（只在 main.py 載一次）
10. 建立 `skills_store/` 或 `data/skills/` 目錄讓 SkillStore 可實際持久化

### 🟠 設計改善（需 review + 測試）

11. 提取 BackgroundAgent 和 Router 的共同 ReAct loop 到基底類別
12. 刪除未使用的 `MemoryIndex` 或整合進 `LongTermMemory`
13. 決定 `paths.py` 是否真的成為路徑單一事實來源（目前是但實際沒人在用）
14. 清理 .env 的舊版 token 名稱
15. 決定 frozen/property 哪個方向，統一 `HavenConfig`

---

*審計完成。建議在清理前先確認備份無誤。*
