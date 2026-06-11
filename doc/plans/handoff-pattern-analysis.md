# Haven — /handoff 模式分析與參考建議

建立日期：2026-06-11
來源分析：[Matt Pocock - /handoff is my new favourite skill](https://www.youtube.com/watch?v=dtAJ2dOd3ko)
討論背景：與 Cris 在 Discord 討論此模式是否適合 KID / Haven

---

## 一、/handoff 是什麼

Matt Pocock 為 Claude Code 開發的 skill，解決 AI coding session 中 context window 塞爆的問題。

核心機制：
- 將當前 session 的上下文壓縮成一份 **markdown 交接文件**
- 存到系統暫存目錄
- 交給一個**全新的 agent session** 接手執行

### 與內建 /compact 的差異

| 面向 | /compact | /handoff |
|------|----------|----------|
| 本質 | 壓縮當前對話 | 產出交接文件給新 session |
| context window | 仍在同一個，繼續膨脹 | 全新乾淨視窗 |
| 適用場景 | 想繼續在同 session 推進 | 想拆成多個 agent 平行工作 |

### 兩種實戰模式

1. **Fire and Forget** — 做到一半需要修 bug，handoff 給另一個 agent 去處理
2. **DIY Sub-agent** — 規劃階段 handoff 出去，子 agent 做完再 handoff 回來合併

---

## 二、對 KID (OpenClaw) 的評估

**結論：OpenClaw 已有更好的等價功能，無需引入 /handoff。**

| 能力 | Matt 的 /handoff | OpenClaw 原生 |
|------|------------------|---------------|
| 觸發方式 | 手動打 `/handoff` | `sessions_spawn` 工具呼叫 |
| 交付物 | markdown 文件 | 直接傳 prompt + context |
| 接收方 | 另一個 Claude Code session | 另一個 agent session |
| 同步方式 | 手動回傳合併 | `sessions_yield` 等待結果 |
| 並行能力 | 手動開多個 terminal | 可 spawn 多個，await 完成 |

OpenClaw 的 sub-agent 機制（sessions_spawn + sessions_yield）本就支援：
- 將任務委派給子 agent
- 等待完成後取回結果
- 多 agent 平行運作

**因此 KID 不需要額外實作 /handoff。**

---

## 三、對 Haven 的評估

### 適合階段

Haven 若發展為 **agentic system**（多 agent 協作架構），handoff 模式值得參考。

### 值得借鑒的設計哲學

1. **Session 邊界管理**
   - 長時間 session 的 context 衰退是每個 agent system 都要面對的問題
   - handoff 概念提供了一種「主動切割 session」的思路

2. **Context 壓縮傳遞**
   - 不是完整複製整個 session history
   - 而是提煉出「下一棒需要知道什麼」的精華
   - 包括：當前進度、關鍵決策、vibe/intent、建議使用的工具

3. **角色分工**
   - 規劃型 agent → 設計架構
   - 執行型 agent → 寫 code
   - 審查型 agent → code review
   - 不同角色透過 handoff 串接

### 不建議現在實作的原因

- Haven Core Prototype 仍在建置階段
- 多 agent 協作需要穩定的底層架構（Router、ToolRegistry、記憶系統）
- 基礎設施未穩之前疊加 handoff 模式只會增加 complexity

### 建議位置

- 納入 `future_skill_system_plan.txt` 的 Phase 3 參考項目
- 或獨立在技術筆記中保留，等 MVP + 技能系統完成後再評估

---

## 四、總結

- /handoff 是一個很好的模式，但 **不是新概念** — 是「把手工作交給另一個人」的工程化實作
- OpenClaw 已有更完整的內建支援（sub-agent spawning）
- Haven 未來可以參考其設計哲學，**不是照抄實作**
- 放入 backlog，不急著做
