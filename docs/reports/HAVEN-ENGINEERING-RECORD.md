# Haven 工程記錄 (Engineering Record)

> 彙整日期: 2026-07-13
> 範圍: Haven 應用層 / 玩法 / 擴展相關的已完成計劃與報告
> 用途: 日後查閱歷史決策

---

## 一、技能與協作架構 (2026-05 ～ 2026-06)

### 技能系統藍圖 (2026-05-29)
- `future_skill_system_plan.md`
- 參考 OpenClaw Skill（SKILL.md，本質上 system prompt 注入 + 工具定義）
- Haven 目前只有靜態 ToolRegistry，需要動態擴充能力
- 設計了 SkillLoader、SkillManifest、hot-reload 機制
- **決定**: MVP 階段先不疊基礎設施，預留接口等穩定後再實作

### /handoff 模式分析 (2026-06-11)
- `handoff-pattern-analysis.md`
- 分析 Matt Pocock 的 /handoff skill (解決 Claude Code context window 塞爆問題)
- 評估是否適合 KID / Haven
- **結論**: 模式有參考價值但不直接套用，Haven 場景不同

### 任務協作層升級 v0.5.3 (2026-06-27)
- `task-orchestration-upgrade-proposal-20260627.md` (提案)
- `task-orchestration-upgrade-report-20260627.md` (實施報告)
- 在三層安全防護之上，疊加任務協作層
- 引入 TaskOrchestrator、SubTaskManager、狀態機
- 關聯: v0.5.2a 安全升級完成後的下一步

---

## 二、設計研究與技術分析

### Claude Code 源碼分析 (2026-06-08)
- `claude-code-design-analysis.md`
- 基於 2026/3 npm 意外洩漏的 4600+ 源碼文件
- 擷取: Tool Registry 模式、Memory 分層、Session 管理、Sandbox 方案
- **對 Haven 參考**: P4+ Roadmap 的直接輸入來源

### 遷移路線圖 (2026-06-08)
- `haven-migration-roadmap.md`
- 從 Claude Code 設計逐步遷移的策略地圖
- 不中斷原則: 每一步都穩定可回滾
- **決定**: 分多個小 PR/Phase，避免瀑布式大改

---

## 三、系統可靠性工程

### 雙開防禦 (2026-06-11)
- 問題: Telegram Conflict、重複通知
- 方案: Gatekeeper 啟動前檢查 + 雙層防禦
- 已在 Windows .bat launcher 實施

### 測試策略與基線 (2026-06-10)
- `testing-strategy.md`: 兩套測試的斷層分析 (Phase 0-9 / legacy tests/)
- `test-baseline-20260610.md`: 724 passed, 0 failed 基線
- 提出統一測試框架、mock 策略、CI 方案

---

## 四、功能擴展規劃

### 預算追蹤器 Wiring Plan (2026-06-12)
- `budget-tracker-wiring-plan.md`
- BudgetTracker 模組完整存在但從未被 instantiate
- LLM API token 消耗完全沒有追蹤
- **計劃**: 在 main.py 接線，成本可視化
- **狀態**: 計劃階段，未執行

### 任務複雜度評估 Wiring Plan (2026-06-12)
- `task-complexity-wiring-plan.md` + `.append`
- TaskComplexityEstimator 存在但從未被呼叫
- Router/BackgroundAgent 的 ReAct loop 用寫死 max_turns
- **計劃**: 依任務複雜度動態分配推理預算
- **狀態**: 計劃階段，未執行

---

## 五、未來產品構想

### AI 輔助程式交易 (2026-05-29)
- `ai_ea_trading_assistant_plan.md`
- 三層級: Level 1 新聞情緒分析 → Level 2 參數最佳化 → Level 3 策略生成
- **背景**: Cris 正在學習程式交易
- **狀態**: 構想階段，非優先

### 中醫診所管理系統 (2026-06-02)
- `tcm-clinic-system.md`
- 整合型中醫師辦公平台: 診症處方、病歷管理、藥材庫存
- TCMA 數據提取已完成（見下方）
- **狀態**: 📝 構想階段

---

## 六、事件事後分析

### Telegram 無回應事件 RCA (2026-07-12)
- `telegram_outage_rcae.md`
- 現象: Haven 在 Telegram 無法回覆，但仍能發出 OpenClaw 下線通知
- 根因: Telegram bot 連線在長時間 idle 後未正確重建
- 修復: 加入 heartbeat ping + 連線健康檢查
- 關聯: `telegram_outage_incident_report.md` (初報，已被 RCA 取代)

### 風險分析審查 (2026-07-09)
- `risk_analysis_review.md` (KID 覆審)
- 原始 `risk_analysis_report.md` (Haven AI 生成)
- KID 評價: 方向正確但嚴重性被誇大，大部分 findings 對現階段規模屬 false alarm
- 無 urgent 項目

---

## 檔案來源索引

| 原始檔案 | 處理 |
|----------|------|
| ai_ea_trading_assistant_plan.md | → 歸檔（已刪） |
| future_skill_system_plan.md | → 歸檔（已刪） |
| handoff-pattern-analysis.md | → 歸檔（已刪） |
| tcm-clinic-system.md | → 歸檔（已刪） |
| trash-system.md | → 歸檔（已刪） |
| budget-tracker-wiring-plan.md | → 歸檔（已刪） |
| claude-code-design-analysis.md | → 歸檔（已刪） |
| task-complexity-wiring-plan.md + .append | → 歸檔（已刪） |
| task-orchestration-upgrade-proposal-20260627.md | → 歸檔（已刪） |
| task-orchestration-upgrade-report-20260627.md | → 歸檔（已刪） |
| test-baseline-20260610.md | → 歸檔（已刪） |
| testing-strategy.md | → 歸檔（已刪） |
| haven-migration-roadmap.md | → 歸檔（已刪） |
| telegram_outage_incident_report.md | → 歸檔（已刪，RCA 保留） |
| risk_analysis_report.md | → 歸檔（已刪，review 保留） |
| telegram_outage_rcae.md | → 保留（RCA 終版） |
| risk_analysis_review.md | → 保留（KID 覆審） |
