┌─────────────────────────────────────────────────────────────┐
│                  Haven 環境契約                             │
│                  Python 路徑 · API 金鑰 · 服務管理           │
└─────────────────────────────────────────────────────────────┘

【Python 虛擬環境】

需裝依賴的指令碼：
  /mnt/z/Core/.venv/bin/python3 <script.py>

純標準庫指令碼（無 import 外部庫）：
  python3 <script.py>

Haven 本身的 .venv：
  /mnt/z/Haven/.venv/bin/python3

【Discord Bot 管理】

長期服務（systemd）：
  systemctl --user status haven-discord.service
  systemctl --user restart haven-discord.service
  journalctl --user -u haven-discord.service -f

【Telegram Bot 管理】

長期服務（systemd）：
  systemctl --user status haven-telegram.service
  systemctl --user restart haven-telegram.service
  journalctl --user -u haven-telegram.service -f

環境變數：
  HAVEN_TELEGRAM_TOKEN         — Bot API token
  HAVEN_HEARTBEAT_TELEGRAM_CHAT — 心跳聊天室 ID
  HAVEN_TELEGRAM_USERNAME       — Bot username（群組提及用）

指令：
  /start   — 歡迎訊息
  /file    — 上傳檔案
  /status  — 系統狀態

【API 金鑰層級】

主要 LLM：DEEPSEEK_API_KEY（api.deepseek.com）
備援 LLM：OPENROUTER_API_KEY（openrouter.ai）
Discord：HAVEN_DISCORD_TOKEN（Haven 專用）
Telegram：HAVEN_TELEGRAM_TOKEN（Haven 專用）
KID Telegram：TELEGRAM_TOKEN（KID 專用）
郵件工具：EMAIL_APP_PASSWORD（Gmail）

【目錄結構】

所有 Python 程式碼：/mnt/z/Haven/agent/
共享函式庫：/mnt/z/Haven/lib/
測試：/mnt/z/Haven/tests/
既有工具（不可修改）：/mnt/z/Core/mail.py /mnt/z/Core/scan.py
