┌─────────────────────────────────────────────────────────────┐
│                  Haven Agent v1.0                           │
│                  系統總覽                                    │
│                  編寫日期：2026-06-09                        │
└─────────────────────────────────────────────────────────────┘

【目錄結構】

  /mnt/z/Haven/
  ├── agent/               # 共享元件（已退役，保留作參考）
  │   ├── core/            # loop.py, model.py（舊 AgentLoop）
  │   ├── tools/           # discord_file_tool.py 等舊工具
  │   └── tool_output.py   # ToolOutput contract（Router 有用）
  │
  ├── dev/kid/             # ★ 主要程式碼（Router）
  │   ├── core/            # Router, Provider, ToolRegistry
  │   │   ├── router.py         # ReAct loop（多輪 tool calling）
  │   │   ├── http_provider.py  # HTTP API 供應商
  │   │   ├── tool_registry.py  # 工具註冊同政策執行
  │   │   ├── tool_decorator.py # @tool 裝飾器
  │   │   ├── policy.py         # 每工具政策（rate limit, timeout）
  │   │   ├── categories.py     # 工具分類
  │   │   ├── scheduler.py      # 排程引擎
  │   │   ├── task_manager.py   # 背景任務管理
  │   │   ├── pending_file.py   # 跨平台檔案傳送排隊
  │   │   └── paths.py          # 路徑設定
  │   │
  │   ├── tools/           # 19 個工具
  │   │   ├── cmd.py           # execute_command
  │   │   ├── read.py          # read_file
  │   │   ├── write.py         # write_file
  │   │   ├── search.py        # web_search
  │   │   ├── send_file.py     # send_file（全新 Universal）
  │   │   ├── send_msg.py      # 跨任務通訊
  │   │   ├── memory_search.py # 長期記憶
  │   │   ├── background_task.py
  │   │   ├── spawn_tool.py    # 子任務
  │   │   ├── task_query.py    # 任務查詢
  │   │   ├── schedule_tool.py # 排程管理
  │   │   ├── set_model.py     # 模型切換
  │   │   └── ...              # 其餘輔助工具
  │   │
  │   ├── transport/       # 平台傳輸層
  │   │   ├── discord_bot.py   # Discord 連接
  │   │   └── telegram_bot.py  # Telegram 連接
  │   │
  │   ├── learning/        # 技能學習系統
  │   ├── soul/            # 記憶系統
  │   └── main.py          # ★ 入口點
  │
  ├── haven_discord.py     # （已退役）
  ├── haven_telegram.py    # （已退役）
  ├── RETIRED.md           # 退役記錄
  ├── 使用說明_v1.0.txt    # 本文件（用戶指引）
  └── overview_v1.0.txt    # 本文件（系統總覽）

【架構設計】

  Router 係一個多輪 ReAct loop：

  使用者輸入
      ↓
  Router.process() 接收訊息
      ↓  ┌─────────────────────────┐
      ↓  │ 重複直到模型直接回覆      │
      ↓  │                         │
      模型（DeepSeek / OpenRouter）│
      ↓  │                         │
      ├── tool_calls？→ 執行工具    │
      │     ↓                     │
      │  結果餵返模型             │
      │     ↓                     │
      └── 繼續循環 ──────────────┘
      ↓
  Router 回覆文字
      ↓
  Transport 層檢查 PendingFileStore
      ├── 有 file → 用原生 API 傳送
      │     Discord → discord.File
      │     Telegram → InputFile
      └── 冇 file → 直接 send 文字

【Provider 系統】

  Primary:  DeepSeek v4 Flash
    端點：api.deepseek.com/v1/chat/completions
    模型：deepseek-v4-flash

  Fallback: OpenRouter
    端點：openrouter.ai/api/v1/chat/completions
    模型：google/gemma-4-26b-a4b-it

  失敗自動 fallback，唔會停頓。

【Transport 層】

  Discord:
    - 用 discord.py library
    - 支援 DM 同頻道 @mention
    - 檔案用 discord.File 原生傳送
    - Token: HAVEN_DISCORD_TOKEN

  Telegram:
    - 用 python-telegram-bot library
    - 支援 DM 同群組
    - 檔案用 InputFile + reply_document 傳送
    - Token: HAVEN_TELEGRAM_TOKEN

  兩個 transport 共用同一個 Router instance，
  每個使用者獨立 session（discord:user_id / telegram:user_id）。

【ToolOutput Contract】

  所有工具執行結果統一格式：

    {
      "status": "success" | "failure",
      "data": 執行結果（成功時）,
      "error": {"code": "ERROR_CODE", "message": "...", "retryable": true/false},
      "meta": {"exec_ms": 123, "truncated": false}
    }

  Error Codes:
    FILE_NOT_FOUND, FILE_TOO_LARGE, TIMEOUT,
    PERMISSION_DENIED, API_ERROR, UNKNOWN

【排程系統】

  支援定時任務（類似 cron）：
  - 任務到期自動執行
  - Persist 喺 schedules.json
  - 重啟後自動恢復
  - 支援新增/移除/暫停/繼續

【背景任務】

  獨立背景子任務，唔 block 主對話：
  - 最多 5 個 concurrent
  - Persist 喺 tasks.json + tasks_archive.json
  - 支援跨任務通訊（MessageBus）
  - 重啟後自動恢復

【技能學習（Phase 3）】

  Haven 會觀察工具使用模式，自動學習：
  - 邊個工具常用
  - 邊種參數組合有效
  - 成功/失敗率
  然後動態調整系統 prompt，提升效率。

【歷史紀錄】

  - 每個使用者獨立 session
  - Session 自動儲存
  - 超過 5 條訊息自動摘要入長期記憶
  - /clear 清除當前 session

【開發規範】

  - CONVENTIONS_EN.md 係主要規範
  - 每 file 上限 400 行
  - 強型別 + Pydantic v2
  - Guard clause pattern
  - 工具用 @tool 裝飾器註冊
  - Test-First (TDD-Lite)
  - 260+ tests，全部通過
