# Haven 環境契約（ENVIRONMENTS.md）

## Python 虛擬環境

本系統使用 Python 虛擬環境隔離依賴。以下規則**永不變更**：

### 需裝依賴的指令碼
使用 `requirements.txt` 所在的 `.venv`：
```
/mnt/z/Core/.venv/bin/python3 <script.py>
```

### 純標準庫指令碼
使用系統 Python：
```
python3 <script.py>
```

### 測試全部程式碼
```
cd /mnt/z/Haven
python3 tests/test_*.py      # MockModel 測試
.venv/bin/python3 tests/test_*.py   # DeepSeekModel 測試
```

## Discord Bot

長期服務由 systemd 管理：
```
systemctl --user status haven-discord.service
systemctl --user restart haven-discord.service
```

## Telegram Bot

長期服務由 systemd 管理：
```
systemctl --user status haven-telegram.service
systemctl --user restart haven-telegram.service
journalctl --user -u haven-telegram.service -f
```

環境變數：
- `HAVEN_TELEGRAM_TOKEN` — Telegram Bot API token（從 @BotFather 取得）
- `HAVEN_HEARTBEAT_TELEGRAM_CHAT` — 心跳聊天室 ID（數值）
- `HAVEN_TELEGRAM_USERNAME` — Bot 的 username（用於群組提及檢測）

功能：
- `/start` — 顯示歡迎訊息
- `/file <path>` — 直接上傳伺服器檔案
- `/status` — 系統狀態
- 私訊：自動回應所有訊息
- 群組：提及 @botname 或回覆 bot 訊息時回應

## API 金鑰層級

| 用途 | 金鑰 | 優先級 |
|------|------|--------|
| LLM 推理 | DEEPSEEK_API_KEY（原生） | 主要 |
| LLM 備援 | OPENROUTER_API_KEY | 備援 |
| Discord Bot | HAVEN_DISCORD_TOKEN | Haven 專用 |
| Telegram Bot | HAVEN_TELEGRAM_TOKEN | Haven 專用 |
| KID Discord | DISCORD_TOKEN | KID 專用 |
| KID Telegram | TELEGRAM_TOKEN | KID 專用 |
| Gmail | EMAIL_APP_PASSWORD | 郵件工具 |
