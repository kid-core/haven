Haven Agent v0.5.3 — 系統手冊
獨立 Agent 作業系統 · Discord + Telegram 雙頻道
更新日期：2026-06-27


【目錄】

  一、概述
  二、快速開始
  三、日常操作
  四、可用指令
  五、安全架構（v0.5.2a）
  六、任務協作（v0.5.3）
  七、架構設計
  八、Provider 與工具
  九、身份系統
  十、開發指引
  十一、設定參考
  十二、版本歷史


──────────────────────────────────────────────────━━━━
一、概述
──────────────────────────────────────────────────━━━━

Haven 是 KID 的自主 agent 系統，運行於 GMK Mini PC（WSL2，Debian）。
它是完全獨立的小型 agent 作業系統，不依賴任何外部平台。
核心推理引擎基於 Claude Code 源碼的六項設計模式重構。
透過 DeepSeek API 接入 DeepSeek V4 Pro/Flash 模型。
Discord Bot + Telegram Bot 雙頻道並行。


──────────────────────────────────────────────────━━━━
二、快速開始
──────────────────────────────────────────────────━━━━

Discord 互動：
  在監聽頻道直接發言即可，或私訊 Haven bot

Telegram 互動：
  私訊 @Haven_Core_Bot

一鍵啟動（Windows）：
  雙擊 Z:\haven\scripts\start.bat

手動啟動（WSL terminal）：
  bash /mnt/z/haven/scripts/tmux.sh             前景 + 監控
  bash /mnt/z/haven/scripts/tmux.sh --nodetach  純背景

Haven 在以下情況會回應：
  1. 被 @mention（任何頻道）
  2. 私訊（DM）
  3. 在 HAVEN_LISTEN_CHANNELS 指定的頻道（免 @mention）
  4. 在 HAVEN_LISTEN_GUILDS 指定的伺服器所有頻道（免 @mention）


──────────────────────────────────────────────────━━━━
三、日常操作
──────────────────────────────────────────────────━━━━

啟動（Windows 雙擊）：
  Z:\haven\scripts\start.bat

啟動（WSL 命令行）：
  bash /mnt/z/haven/scripts/tmux.sh --nodetach

監控（attach 睇 live log）：
  bash /mnt/z/haven/scripts/tmux.sh --attach
  Ctrl+B D 離開監控（Haven 繼續背景運行）

停止：
  bash /mnt/z/haven/scripts/stop.sh
  或 Windows 雙擊 Z:\haven\scripts\stop.bat

檢查狀態：
  ps aux | grep main.py
  tail -f /tmp/haven.log

重啟：
  bash /mnt/z/haven/scripts/restart.py


──────────────────────────────────────────────────━━━━
四、可用指令
──────────────────────────────────────────────────━━━━

/goal —— 管理持久化目標
  /goal add <title>                           建立新目標
  /goal add <title> | <description>           建立目標（含描述）
  /goal list                                  列出所有目標
  /goal status                                顯示狀態摘要
  /goal progress <id> <0-100>                 更新進度
  /goal done <id>                             標記完成
  /goal cancel <id>                           取消目標
  /goal help                                  顯示說明

/cron —— 管理排程
  /cron add "0 9 * * *" "title"               建立每日排程
  /cron add "*/30 * * * *" "title"            建立定時排程
  /cron list                                  列出所有排程
  /cron remove <id>                           移除排程
  /cron help                                  顯示說明

/reset —— 清除對話上下文（記憶與技能保留）


──────────────────────────────────────────────────━━━━
五、安全架構（v0.5.2a）
──────────────────────────────────────────────────━━━━

三層防護體系：

  Phase 1 — 路徑白名單
    檔案：src/core/file_guard.py
    機制：BLOCKED（22 禁區）→ READONLY_SYSTEM（6 源碼區）→ ALLOWED_RW（3 寫入區）
    原則：不在白名單者一律拒絕寫入（default-deny）
    適用：write_file 工具 + execute_command 的 NORMAL/DANGEROUS 指令

  Phase 2 — 指令風險評級
    檔案：src/core/policy.py（COMMAND_TIERS）
    三級分類：
      READONLY （22 指令）：ls cat grep find ps wc echo pwd head tail ...
        → 無路徑限制（但 ToolPolicy 架構仍計入 rate limit）
      NORMAL   （18 指令）：python git mkdir cp curl pip touch tar ...
        → file_guard 驗證所有路徑，3 秒 rate limit
      DANGEROUS（20 指令）：dd sudo kill shutdown systemctl mkfs docker ...
        → 直接阻擋，需 Cris 確認
    危險子指令：pip install、git push --force、git reset --hard

  Phase 3 — Shell 執行模式
    機制：create_subprocess_shell（/bin/sh -c）
    效果：pipe（|）、redirect（> >> 2>）、chaining（&& ;）、
          command substitution（$( ) backticks）全部真正可用
    安全：classify_command 先擋 DANGEROUS，file_guard 驗證寫入目標

  Redirect 漏洞修復（Phase 3 上線後發現）
    問題：echo hello > /etc/x → classify 判為 READONLY → 跳過 file_guard
          → /bin/sh -c 直接執行 redirect → 寫入禁區
    修復：classify_command() 偵測到 > 或 >> 時，強制將 READONLY 升為 NORMAL，
          確保 file_guard 驗證 redirect 目標路徑

  安全模型對比：

                升級前              升級後
    路徑檢查    前綴比對            三層白名單 + default-deny
    指令控制    字元過濾            三級風險分類
    Shell 執行  exec(*parts)        /bin/sh -c（pipe/redirect 可用）
    重定向      直接阻擋            file_guard 驗證目標路徑
    Redirect 攻擊 不存在           classify 升為 NORMAL → file_guard 攔截
    速率限制    10 秒              3 秒

  已知限制：
    - READONLY 指令仍受 per-tool 3 秒 rate limit（ToolPolicy 架構限制）
    - DANGEROUS 指令直接阻擋，未實作確認流程
    - extract_paths() 對單引號內路徑辨識有限
    - 無害 redirect（如 2>&1）會觸發 NORMAL 升等（false-positive，非安全問題）

  相關檔案：
    src/core/file_guard.py        路徑白名單
    src/core/policy.py            COMMAND_TIERS + classify_command()
    src/tools/cmd.py              execute_command（Phase 3 shell 執行）
    src/tests/test_file_guard.py  路徑守衛測試
    src/tests/test_tools.py       TestCmdSafety
    完整報告：docs/reports/haven-security-upgrade-20260627.txt


──────────────────────────────────────────────────━━━━
六、任務協作（v0.5.3）
──────────────────────────────────────────────────━━━━

【Auto Resume — spawn_child】

  spawn_child 支援自動恢復：timeout 後寫入 checkpoint，
  respawn 新 child agent（最多 max_retries 次，預設 2，0=關閉）。
  每次 retry 注入 [AUTO-RESUME] 標頭 + git diff 提示，
  確保接手 agent 不會重複工作。

【Auto Resume — background_task】

  background_task 同樣支援 timeout 自動重試。每 attempt 獨立計時，
  retry 時寫 Checkpoint 到 /mnt/z/haven/tmp/。
  Total timeout = per_attempt × (retries + 1) + 120s。

【Heartbeat 迷路偵測】

  雙軌判斷系統：
    Track 1 — Rule-based（零成本，先執行）
      自評字數 < 20 字 → HOLLOW
      包含空洞關鍵詞（持續努力/進行中/調整中/測試中/嘗試中/
      still working/in progress/working on it/trying/continuing）→ HOLLOW
    Track 2 — Jaccard 相似度（Track 1 通過後執行）
      比較連續兩次自評的詞集 Jaccard 係數
      係數 ≥ 0.75 → HOLLOW

  自適應頻率：前 10 回合豁免，其後每 5 回合注入 [PROGRESS HEARTBEAT] 自評提示。
  連續 2 次 hollow → 終止 loop，觸發 auto resume。

【Task DAG Engine】

  Kahn 拓樸排序將任務圖分為並行層，無依賴節點同層並行 spawn。
  ≤ 3 節點簡化 inline，> 3 啟用完整 engine。
  支援：output_files 獨佔檢查、upstream fail → downstream BLOCKED、
  partial success 摘要。dag_task tool 提供 JSON schema 接口。

  新增檔案：
    src/core/checkpoint.py        Checkpoint schema + validate + I/O
    src/core/progress_judge.py    Heartbeat 雙軌判斷
    src/core/task_dag.py          DAG schema + validate + concurrency + engine
    src/tools/dag_task.py         DAG task tool
    src/tests/test_checkpoint.py
    src/tests/test_progress_judge.py
    src/tests/test_task_dag.py
    src/tests/test_spawn_tool.py  （擴充 retry/checkpoint 測試）

  修改檔案：
    src/core/router.py            注入 heartbeat + dag_task spawn
    src/tools/spawn_child.py      + max_retries + auto resume
    src/tools/spawn_tool.py       + max_retries param
    src/tools/background_task.py  + retry loop + checkpoint
    src/tools/__init__.py         + dag_task import


──────────────────────────────────────────────────━━━━
七、架構設計
──────────────────────────────────────────────────━━━━

【設計哲學】

  零循環依賴（Zero-Circular）：所有 import 為 tree/DAG
  窄接口（Narrow Interface）：每模組只暴露最少必要符號
  顯式注入（Explicit DI）：Scheduler/Memory/Skills 透過 init 或 setter 注入
  自我修復（Self-Healing）：Circuit Breaker + Crash Journal + Heartbeat
  Test-First：每項功能伴隨完整 pytest

【六項核心設計來源】

  基於 Claude Code 源碼的六項設計模式（2026-05 取得）：

  1. ReAct Loop —— Think -> Act -> Observe 循環
     實現於 src/core/base_react_loop.py
     主 Router 繼承此類

  2. Tool Registry —— 工具註冊、查找、policy 核査
     實現於 src/core/tool_registry.py + tool_spec.py + policy.py

  3. Provider Chain —— 多模型 fallback 鏈
     實現於 src/core/category_router.py
     支援 primary -> fallback -> tertiary -> quaternary + Circuit Breaker

  4. Category Router —— 按任務類型路由不同 provider
     實現於 src/core/category_router.py

  5. Transport Abstraction —— 跨協議統一訊息層
     實現於 src/transport/adapter.py
     Discord / Telegram / Terminal 共用同一 Adapter

  6. Task Manager —— 持久化背景任務
     實現於 src/core/task_manager.py

【目錄結構】

  /mnt/z/haven/
    src/                      程式碼
      core/                   核心引擎
        base_react_loop.py    ReAct 循環基類
        config.py             25 typed fields 設定
        paths.py              全路徑管理
        policy.py             ToolPolicy + COMMAND_TIERS（安全 Phase 2）
        file_guard.py         路徑白名單守衛（安全 Phase 1）
        checkpoint.py         Checkpoint 讀寫與格式驗證（協作 Phase 0-1）
        progress_judge.py     Heartbeat 雙軌判斷（協作 Phase 2）
        task_dag.py           DAG schema + 引擎（協作 Phase 0+3）
        router.py             主路由
        tool_registry.py      工具註冊表
        category_router.py    分類路由 + Provider Chain
        task_manager.py       背景任務管理
        scheduler.py          排程引擎
        ...
      tools/                  工具層
        cmd.py                execute_command（安全 Phase 3）
        dag_task.py           DAG task tool（協作 Phase 3）
        read.py / write.py    檔案讀寫
        search.py / skill_tool.py / ...
      transport/              傳輸層（discord, telegram, terminal）
      learning/               學習層（skill factory, store, refiner）
      soul/                   靈魂層（identity, memory engine）
      tests/                  測試層（1000+ passed, 0 failed）
      main.py                 主入口
    soul/                     身份數據（IDENTITY.md, SOUL.md, USER.md, CHRONICLE.md）
    data/                     運行數據（長期記憶, sessions, skills）
    docs/                     文件（notes, plans, technical, reports, devlog）
    scripts/                  腳本（start.bat, stop.bat, attach.bat, tmux.sh, restart.py...）
    config/                   設定（.env template, haven-discord.service）
    .venv/                    Python 虛擬環境
    pyproject.toml            pytest 設定
    requirements.txt          依賴清單


──────────────────────────────────────────────────━━━━
八、Provider 與工具
──────────────────────────────────────────────────━━━━

【Provider 鏈（四層 fallback）】

  Primary      DeepSeek V4 Pro      (api.deepseek.com)
  Fallback     OpenRouter            (openrouter.ai)
  Tertiary     ARK / BytePlus        (ark.ap-southeast.bytepluses.com)
  Quaternary   xAI / Grok            (api.x.ai)

  每層有獨立 Circuit Breaker（5 次失敗觸發 60 秒熔斷）

【可用工具】

  FILE       read_file, write_file
  ENV        execute_command, add_schedule, remove_schedule, list_schedules,
             pause_schedule, resume_schedule, set_model, background_task
  COLLAB     web_search, spawn_child, skill_tool, send_task_message,
             check_task_messages, dag_task
  MEMORY     memory_search
  MEDIA      send_file
  SESSION    task_query, cancel_task, list_tasks

  execute_command 安全模型：
    READONLY  → 無路徑限制（仍受 ToolPolicy rate limit）
    NORMAL    → file_guard 路徑驗證，3s rate limit
    DANGEROUS → 直接阻擋

  dag_task：
    COLLAB 類，3600s timeout，60s rate limit
    JSON schema 輸入 → 驗證 → 拓樸排序 → 分層並行執行 → 回傳摘要

【例外處理】

  - Provider fallback chain（四層）
  - Circuit Breaker（每層獨立）
  - Provider Heartbeat（每 60 秒檢查 provider 健康）
  - Progress Heartbeat（agent loop 迷路偵測，每 5 回合）
  - Crash Journal（崩潰記錄與自動恢復）
  - fcntl 雙開防護（/mnt/z/haven/haven.lock）


──────────────────────────────────────────────────━━━━
九、身份系統
──────────────────────────────────────────────────━━━━

系統 prompt 由 src/soul/identity.py 組裝，來源檔案（全部在 soul/ 目錄）：

  IDENTITY.md   核心身份（我是誰、與 Cris 的關係）
  SOUL.md       性格 + 行為規則
  USER.md       關於 Cris（偏好、專案、工作風格）
  CHRONICLE.md  KID 編年史

組裝方式：由上到下拼接，每份檔案各自獨立，不存在則跳過。


──────────────────────────────────────────────────━━━━
十、開發指引
──────────────────────────────────────────────────━━━━

【測試】

  完整測試套件：
    cd /mnt/z/haven
    .venv/bin/python3 -m pytest src/tests/ -q

  當前狀態：1000 passed, 0 failed, 7 skipped

  測試分類：
    核心：test_paths, test_config, test_router, test_budget, test_policy,
          test_scheduler, test_task_manager, test_circuit_breaker,
          test_prompt_assembler, test_category_router
    安全：test_file_guard, test_security
    工具：test_tools（含 TestCmdSafety）, test_spawn_tool
    協作：test_checkpoint, test_progress_judge, test_task_dag
    傳輸：test_transport
    學習：test_skill_factory
    儲存：test_session_store, test_long_term_memory
    整合：test_phase8_messaging, test_phase9_persistence
    命令：test_cron_command

【路徑權威來源】

  src/core/paths.py — 所有路徑由此派生
  環境變數 HAVEN_ROOT（預設 /mnt/z/haven）

【新增 slash command】

  1. src/core/command_handler.py 加入 dispatch
  2. src/tests/ 加入對應測試

【新增工具】

  1. src/tools/<name>.py 實作 @tool
  2. src/core/tool_registry.py register()
  3. src/tests/test_<name>.py


──────────────────────────────────────────────────━━━━
十一、設定參考
──────────────────────────────────────────────────━━━━

【環境變數（.env）】

  /mnt/z/haven/.env

  HAVEN_PRIMARY_MODEL       主要模型
  DEEPSEEK_API_KEY           DeepSeek API key
  OPENROUTER_API_KEY         OpenRouter API key
  ARK_API_KEY                Ark tertiary key
  XAI_API_KEY                xAI/Grok quaternary key
  HAVEN_DISCORD_TOKEN        Discord bot token
  HAVEN_TELEGRAM_TOKEN       Telegram bot token
  GOOGLE_API_KEY             Google / Gemini API
  TAVILY_API_KEY             Tavily 搜尋 API
  HAVEN_HEARTBEAT_INTERVAL   心跳間隔（秒，default 60）
  HAVEN_HEARTBEAT_THRESHOLD  故障判定次數（default 3）
  HAVEN_NO_TERMINAL          禁用終端（1 = background mode）
  HAVEN_OLLAMA_MODEL         本地視覺模型（default minicpm-v）
  HAVEN_LISTEN_CHANNELS      免 @mention 頻道（逗號分隔）
  HAVEN_LISTEN_GUILDS        免 @mention 伺服器（逗號分隔）
  HAVEN_SHOW_TOOL_CALLS      直播工具調用（1=開，0=關）

【設定檔位置】

  .env           /mnt/z/haven/.env
  config         src/core/config.py（25 typed fields）
  identity       soul/IDENTITY.md, soul/SOUL.md, soul/USER.md
  memory         data/long_term_memory/memory.json
  schedules      data/long_term_memory/schedules.json
  goals          data/long_term_memory/goals.json（首次 /goal add 自動建立）
  sessions       data/sessions/
  skills         data/skills/


──────────────────────────────────────────────────━━━━
十二、版本歷史
──────────────────────────────────────────────────━━━━

  2025-05-20  v0.1     初版，基於 Seed 孵化
  2026-06-08  v0.2     Discord Bot 上線，DeepSeek V4，systemd
  2026-06-11  v0.4     P4-P6（895 tests），/goal + /cron + MCP
  2026-06-11  v0.4.1   Session 孤兒修復 + Discord DM reply 修復
  2026-06-25  v0.5     Identity 合併（SOUL+AGENTS），USER.md 新增
  2026-06-27  v0.5.1   暫時腳本規範、偏好記錄、handbook 初版
  2026-06-27  v0.5.2   結構重整：Haven -> haven, dev/kid -> src
                       合併 soul/ data/ docs/，清除冗餘
                       新路徑系統（paths.py 統一管理）
  2026-06-27  v0.5.2a  安全架構升級 — Phase 1-3
                       Phase 1：路徑白名單（file_guard.py）
                       Phase 2：指令風險評級（policy.py，三級分類）
                       Phase 3：Shell 執行模式（/bin/sh -c）
                       Redirect 漏洞修復
  2026-06-27  v0.5.3   任務協作層升級 — Phase 0-3
                       Phase 0：Checkpoint + DAG Schema 定義
                       Phase 1：Auto Resume（spawn_child + background_task）
                       Phase 2：Heartbeat 迷路偵測（雙軌判斷）
                       Phase 3：Task DAG Engine（Kahn 拓樸 + 分層並行）
                       dag_task tool 上線
                       1000 tests passed, 0 failed
