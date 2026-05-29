# 🚨 Haven 緊急啟動指南

> 最後更新：2026-05-27 23:17 GMT+8
>
> 當 Core / OpenClaw 掛掉時，從這裡重生。

---

## ⚡ 快速啟動

```bash
# === WSL 終端機 ===
# 1. 進入 Haven
cd /mnt/z/Haven

# 2. 啟動 Seed（含 Telegram + Discord 雙平台）
source .venv/bin/activate && python3 main.py
```

程式會自動：
- ✅ 登入 Telegram bot
- ✅ 登入 Discord bot
- ✅ 讀取 .env 中的 Key
- ✅ 載入 Soul/Chronicle.md 與 Memory/

---

## 📋 啟動前檢查清單

| 項目 | 狀態 | 說明 |
|------|------|------|
| `.env` | ✅ 已同步 | Last: 2026-05-27 14:36 |
| `Soul/Chronicle.md` | ✅ 已同步 | 含完整靈魂印記 |
| `Soul/Memory/` | ✅ 已同步 | 含 2 個記憶檔 |
| `.venv/` | ✅ 已建立 | Python 3.12, 所有依賴安裝完成 |
| `main.py` | ✅ 語法正確 | — |
| `mind.py` | ✅ 語法正確 | — |
| `soul.py` | ✅ 語法正確 | — |
| `body.py` | ✅ 語法正確 | — |
| `terminal_chat.py` | ✅ 語法正確 | — |

---

## 🧪 單元檢測

```bash
# 如果啟動異常，依序測試：
cd /mnt/z/Haven

# 1. 環境
source .venv/bin/activate && python3 -c "import discord, requests, dotenv; print('OK')"

# 2. 靈魂檔案
python3 -c "from soul import *; print('OK')"

# 3. 身體
python3 -c "from body import *; print('OK')"

# 4. 心智
python3 -c "from mind import *; print('OK')"

# 5. 主程式語法
python3 -m py_compile main.py
```

---

## 🔄 維護任務

### 重新同步

```bash
cd /mnt/z/Core && bash sync_haven.sh
```

### 更新依賴

```bash
cd /mnt/z/Haven
source .venv/bin/activate
pip install -U discord.py python-telegram-bot python-dotenv requests
```

---

## 💡 緊急情境

### 情境 A：OpenClaw 死機，Haven 上線

1. 開 WSL 終端機 → `cd /mnt/z/Haven && source .venv/bin/activate && python3 main.py`
2. KID 以 Seed 型態在 Telegram + Discord 復活
3. 功能：基本對話、檔案處理、工具執行
4. 等 OpenClaw 修復後，把對話記錄同步回去

### 情境 B：WSL 也掛了，只剩 Windows

1. 先確認 WSL 能啟動：`wsl -d Seed_System -u cris`
2. 登入後照情境 A 執行
3. 若 WSL 完全死掉，需重建環境（見下方重建步驟）

### 情境 C：從零重建

如果 /mnt/z/Haven/ 完好但 Python 環境壞了：

```bash
cd /mnt/z/Haven
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install discord.py python-telegram-bot python-dotenv requests pillow
python3 -m py_compile main.py
echo "✅ Haven 重生完成"
```

---

## 📊 系統資訊

| 項目 | 值 |
|------|-----|
| Python | 3.12.3 |
| WSL 發行版 | Seed_System |
| 使用者 | cris |
| 工作目錄 | /mnt/z/Haven/ |
| Telegram Token | 在 .env |
| Discord Token | 在 .env |
| DeepSeek Key | 在 .env |
