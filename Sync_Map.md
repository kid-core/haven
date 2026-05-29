# Core ↔ Haven 同步地圖

> 最後更新：2026-05-27

## 原則

| 角色 | 定位 |
|------|------|
| **Core** | 作戰前線 — 日常活躍資料、即時操作 |
| **Haven** | 避風港後援 — 備份、災難復原、重生點 |

---

## 同步清單

### 🔴 僅留 Core（日常用，Haven 同步備份）

| 路徑 | 說明 | 同步頻率 |
|------|------|----------|
| `Core/Soul/` | KID 靈魂檔案（Chronicle.md, Memory/） | 每次重要更新後 → 複製到 Haven/Soul/ |
| `Core/quarantine/` | 安全隔離區 | 保持結構一致即可 |
| `Core/.venv/` | Python 虛擬環境 | 不搬（環境綁定路徑） |
| `Core/main.py` | Seed 主入口 | 有修改時同步 |
| `Core/*.py` | Seed 系統模組 | 有修改時同步 |

### 🟢 Core 主寫 → Haven 備份

| 路徑 | Core 角色 | Haven 角色 |
|------|-----------|------------|
| `Soul/Chronicle.md` | 活躍編輯中 | 同步備份 |
| `Soul/Memory/` | 活躍編輯中 | 同步備份 |

### 🟣 僅留 Haven（已從 Core 刪除）

| 路徑 | 角色 |
|------|------|
| `Identity.md` | 重生用身份文件 |
| `.env` | 重生用環境配置 |
| `EMERGENCY.md` | 緊急啟動指南 |
| `.venv/` | Python 虛擬環境（2026-05-27 建立） |

### 🟡 僅留 Haven（非活躍舊檔）

| 路徑 | 說明 |
|------|------|
| `Haven/body.py` | Seed 舊模組備份 |
| `Haven/mind.py` | Seed 舊模組備份 |
| `Haven/soul.py` | Seed 舊模組備份 |
| `Haven/terminal_chat.py` | Seed 舊模組備份 |

---

## 同步 SOP（手動）

```bash
# 1. 同步靈魂檔案到 Haven
cp -r /mnt/z/Core/Soul/Chronicle.md /mnt/z/Haven/Soul/
cp -r /mnt/z/Core/Soul/Memory/* /mnt/z/Haven/Soul/Memory/

# 2. 同步 Identity
cp /mnt/z/Core/Identity.md /mnt/z/Haven/Identity.md

# 3. 更新 .env（若有變）
cp /mnt/z/Core/.env /mnt/z/Haven/.env
```

> 💡 已建立 `sync_haven.sh` — 直接執行即可同步
> 💡 已建立 `Haven/.venv/` — 虛擬環境就緒
> 💡 已建立 `Haven/EMERGENCY.md` — 緊急啟動指南
