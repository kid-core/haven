# Telegram 無回應事件：根因分析報告 (Root Cause Analysis)

**日期**: 2026-07-12
**事件**: Haven 在 Telegram 上無法回覆用戶訊息，但仍能發出 OpenClaw 下線通知
**分析者**: Haven AI (Architect Mode)
**狀態**: 待修復 (Fix Pending — 建議交由 Kid 執行)

---

## 1. 現象描述 (Symptoms)

| 現象 | 狀態 |
|:---|:---:|
| Telegram 接收用戶訊息並回覆 | ❌ 失效 |
| Telegram 主動推送通知（如 OpenClaw 下線警報）| ✅ 正常 |
| Discord 所有功能 | ✅ 正常 |
| Terminal 所有功能 | ✅ 正常 |

**關鍵矛盾點**：Telegram 的「發送」通道正常，但「接收」通道失效。這指向 polling 機制已中斷，而 bot API 實例本身仍存活。

---

## 2. 根因分析 (Root Cause)

### 2.1 主要缺陷：Task 監控遺漏 (`src/main.py`)

在 `main.py` 的啟動流程中，Discord 與 Telegram 的任務監控存在不對稱：

```python
# ✅ Discord — task 被納入主循環監控
discord = run_discord(router, command_handler=command_handler)
tasks.append(discord.task)

# ❌ Telegram — task 未被納入監控（遺漏）
telegram = run_telegram(router, command_handler=command_handler)
# 缺少: tasks.append(telegram.task)
```

**影響鏈**：

```
telegram.task 未被監控
  → _start() 中的 polling 因網路抖動/API限流而中斷
    → 無人感知（主循環不追蹤此 task）
      → handle_message 不再被觸發
        → Telegram 無回應
```

### 2.2 為何「發送」仍正常？

`telegram.notify()` 是透過 `self.app.bot.send_message()` 直接呼叫 Telegram Bot API。Bot 實例在 `_start()` 中的 `app.initialize()` 階段已建立，只要初始化曾成功過，bot 實例就持續有效——即使 polling 已死。

```
_start() 的執行流:
  await app.initialize()  ← Bot 實例建立（成功）
  await app.start()       ← 應用啟動
  await app.updater.start_polling()  ← polling 開始（後續中斷）
  
若 polling 中斷:
  app.bot 仍有效 → notify() 可發送 ✅
  updater 已死 → handle_message 不觸發 ❌
```

### 2.3 次要隱患：回調簽名不一致 (`src/transport/telegram_bot.py`)

```python
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, adapter.handle_message))
```

`handle_message` 簽名為 `(self, msg: Any)`，但 python-telegram-bot v20+ 的回調規範為 `(update: Update, context: ContextTypes.DEFAULT_TYPE)`。若版本匹配不當，可能導致 `TypeError`。

---

## 3. 修復方案 (Fix Plan)

### 3.1 立即修復（1 行）

**檔案**: `src/main.py`，約第 282 行
**改動**: 在 `run_telegram()` 之後補上 `tasks.append(telegram.task)`

```python
# 修改前
telegram = run_telegram(router, command_handler=command_handler)

# 修改後
telegram = run_telegram(router, command_handler=command_handler)
tasks.append(telegram.task)
```

### 3.2 穩健性加固（建議）

1. **`_start()` 加入自動重試機制**：將 polling 包裝為永久循環，中斷時自動重連
2. **加入 Telegram 健康檢查**：HeartbeatMonitor 應同時檢查 Telegram polling 狀態
3. **回調簽名修正**：確認 PTB 版本，並使 `handle_message` 簽名與之匹配

---

## 4. 時間線推演 (Likely Timeline)

```
[正常運行] Telegram polling 正常
     ↓
[觸發事件] 網路抖動 / Telegram API 限流 / 內部異常
     ↓
[ polling 中斷 ] updater.start_polling() 內部拋出異常
     ↓
[無人感知] telegram.task 未被主循環監控，異常被吞沒
     ↓
[症狀出現] Telegram 收不到訊息，但 notify() 仍可發送
     ↓
[用戶發現] Cris 發現 Telegram 無回應
```

---

## 5. 建議執行者

此修復涉及 `main.py` 啟動流程的核心邏輯，建議交由 **Kid** 執行，以確保修改後的穩定性。

---

*報告由 Haven AI 根據原始碼靜態分析生成。*
