┌─────────────────────────────────────────────────────────────┐
│                  Haven Agent v0.1                           │
│                  KID 的夥伴系統                              │
│                  基於 Claude Code 源碼設計的自主 agent       │
│                  編寫日期：2026-06-08                        │
└─────────────────────────────────────────────────────────────┘


【快速開始】

互動模式：
  python3 haven.py

單次任務：
  python3 haven.py --message "掃描 agent/core/loop.py"

系統狀態：
  python3 haven.py --status

背景守護：
  python3 haven.py --daemon

從 Windows 啟動：雙擊 start_haven.bat


【系統架構】

agent/
  core/          主迴圈（generator 模式，5 階段 pipeline）
  permissions/   權限管理器（3 層檢查）+ 拒絕追蹤器
  compaction/    壓縮管道（3 級，circuit breaker 保護）
  tools/         郵件工具 + 掃描工具 + ToolSearch（延遲載入）
  memory/        KairosMemory（3 層閘門，append-only 日誌）
  avatar/        系統化身（5 項數值，7 種姿態，ASCII 渲染）

lib/
  circuit_breaker.py  斷路器（裝飾器 + 全域註冊表 + 冷卻時間）
  config.py           設定管理（.env + 環境變數）
  logger.py           結構化日誌系統


【處理流程】

使用者輸入
  → 壓縮（3 級：截斷 → 選擇性清理 → 摘要）
  → 思考（模型決定工具與參數）
  → 檢查（3 層權限：規則 → Hook → 預設拒絕）
  → 執行（斷路器保護）
  → 處理（結果整合）
  → 輸出


【子系統詳解】

1. AgentLoop 核心迴圈
   generator 模式，每次 turn() 產出 5 個階段。
   支援暫停/恢復，狀態可 JSON 序列化。
   有 max_turns 保護（預設 100 輪）。

2. 權限框架
   3 層檢查：規則層（O(1)）→ Hook 層（可程式化） →
   預設拒絕。
   拒絕追蹤器（CC 的 46 行設計）：
   連續 3 次或累計 20 次拒絕 → 自動降級手動模式。

3. 壓縮管道
   3 級壓縮，便宜先做：
   第 1 級：截斷超大輸出（O(1)）
   第 2 級：保留近 N 輪 + 所有使用者訊息（O(n)）
   第 3 級：LLM 摘要（有斷路器，最多失敗 3 次）
   第 2 級通過 → 第 3 級跳過。

4. ToolSearch 延遲工具載入
   工具標記 deferred=True 後預設隱藏。
   Agent 呼叫 search("關鍵字") 按需載入。

5. KairosMemory 記憶系統
   3 層閘門控制 consolidation：
   (1) 時間閘 — 距上次 ≥ 24 小時
   (2) Session 閘 — 累積 ≥ 5 個 session
   (3) 鎖定閘 — 取得檔案 advisory lock
   Lock 檔案 mtime = 上次 consolidation 時間。
   失敗時 mtime 不回寫，天然 rollback。

6. 驗證 Agent
   獨立程式碼驗證器。不信任主 agent 寫的程式碼。
   System prompt 列出自我合理化的藉口：
   「程式碼看起來是對的」→ 讀不等於驗證，跑一次。
   「測試已經過了」→ 實現者是 LLM，獨立驗證。
   「大概沒問題」→ 大概不等於已驗證。

7. 系統狀態化身
   5 項數值對應真實系統指標：
   - 除錯：24h crash 次數
   - 耐心：佇列長度/延遲
   - 混亂：壓縮頻率
   - 智慧：consolidation 次數
   - 警戒：異常次數

   7 種 ASCII 姿態：
   睡眠 zZ / 安穩 ^_^ / 活躍 ^o^ /
   緊張 >_< / 警戒 @_@ / 孵化 .o. / 做夢 ~u~
   夜間模式：23:00-08:00 自動睡眠。


【設定】

環境變數：
  HAVEN_MAX_TURNS=10  最大輪次（預設 10）
  HAVEN_MODEL=mock    模型後端（mock/openrouter）


【測試】

python3 tests/test_circuit_breaker.py  Phase 0（24）
python3 tests/test_phase1.py           Phase 1（82）
python3 tests/test_phase2.py           Phase 2（164）
python3 tests/test_phase3.py           Phase 3（116）
python3 tests/test_phase4.py           Phase 4（166）
python3 tests/test_phase5a.py          Phase 5a（65）
python3 tests/test_phase5b.py          Phase 5b（85）

共 702 項測試，0 失敗。


【設計來源】

所有核心架構均取自 Claude Code 洩漏源碼中的設計模式：
- 權限框架：yoloClassifier.ts + denialTracking.ts
- 壓縮管道：五層壓縮簡化為三層
- 斷路器：MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES 的教訓
- ToolSearch：defer_loading + ToolSearch meta-tool
- 驗證 Agent：verificationAgent.ts「AI 不相信 AI」模式
- KairosMemory：autoDream.ts 三層閘門 + lock 設計
- 系統化身：BUDDY pet，重新構想為系統健康指標
