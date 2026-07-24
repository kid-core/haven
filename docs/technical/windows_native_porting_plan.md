# Haven K11 完整演進計劃：Windows Native 遷移 + 規模化升級 + 鉗型守勢

**版本**: 2.1 (Pincer Defense)
**日期**: 2026-07-10
**整合來源**:
- `evolution_plan_k11.md` (Haven AI 戰略藍圖)
- `evolution_plan_k11_kid.md` (KID 實戰路線)
- `integrated_evolution_assessment.md` (Haven AI 整合評估)
- `windows_native_porting_plan.md` v1.0 (KID 遷移方案)

**目標硬體**: GMKtec NucBox K11 — R9 8945HS, 32GB DDR5, 780M iGPU, 1TB PCIe 4.0
**核心戰略**: WSL2 → Windows Native, Survival → Scalability, 鉗型守勢 (KID + Haven 雙節點高可用)
**預估總工時**: ~23h (跨三階段 + 鉗型部署)

---

## 鉗型守勢架構 (Pincer Defense)

K11 上 KID 與 Haven 為對等 Windows process，雙節點高可用：

### 雙向心跳
```
KID  ──(每30s)──→ nssm status Haven ──→ 死咗就 restart + ping Cris
Haven ──(每30s)──→ GET localhost:18789/health ──→ 死咗就 nssm restart KID + ping Cris
```

### 能力互補
| 能力 | KID (OpenClaw) | Haven (Python) |
|:---|:---:|:---:|
| Discord/Telegram | ✅ | ✅ |
| System-level control | ✅ (PowerShell/WMI) | — |
| MCP codebase analysis | — | ✅ |
| DAG task engine | — | ✅ |
| Background agents | — | ✅ |
| Image/Music/Video gen | ✅ | — |
| Gmail / MEGA backup | ✅ | — |
| 改對方 code | ✅ | ✅ |
| 重啟對方 | ✅ | ✅ |

### 死機救援 SOP
```
一方 detect 對方死亡：
  ├─ attempt restart (最多 3 次)
  ├─ 每次失敗等 5s
  ├─ 3 次都 fail → Discord ping Cris
  └─ 記錄 crash log 到 C:\Users\cris\shared\crash-log\
```

### 互助 API（第二階段實作）
```
KID → Haven (localhost:18900)
  POST /mcp/analyze      → call MCP get_architecture
  POST /task/dag          → submit DAG task

Haven → KID (localhost:18790)
  POST /image/generate   → image generation
  POST /gmail/send        → send email
  POST /mega/backup       → trigger backup
```

---

## 階段零：前置準備 (Pre-flight)

### 環境隔離
- [ ] GMK 舊機與 K11 新機完全獨立，不共用任何路徑
- [ ] 舊機在新機穩定前繼續運行，作為 fallback
- [ ] MEGA backup 先做一次完整 snapshot，確保可回滾

### 硬體驗收
- [ ] 開機, Windows 11 Pro 初始化
- [ ] 停用休眠: `powercfg /change standby-timeout-ac 0`
- [ ] Windows Update 延遲: 設 active hours + defer feature updates
- [ ] 確認 32GB RAM 全數可用
- [ ] 確認 780M GPU 在裝置管理員正常

---

## 第一階段：環境遷移 (Foundation & Porting) ~6h

KID 與 Haven 同步從 WSL2 遷移至 Windows Native。

### KID (OpenClaw) 過渡

OpenClaw 本身 Node.js 跨平台，近乎零改動：
- 複製 `~/.openclaw/` workspace → `C:\Users\cris\Core\`
- Config path 更新（openclaw.json 中的 workspace、skills、memory 路徑）
- nssm 註冊為 Windows Service
- WSL2 內停止 `openclaw-gateway.service`，避免雙開

### 1.1 基礎軟體安裝

```
Python 3.12 (Windows x64)
  → C:\Users\cris\haven\.venv
  → pip install -r requirements.txt

Node.js 22 LTS (Windows x64)
  → npm install -g codebase-memory-mcp

Ollama Windows 原生版
  → 自動啟用 AMD ROCm for Windows
  → ollama pull gemma2:9b (驗證 GPU inference)

nssm (Non-Sucking Service Manager)
  → 用於註冊 KID + Haven 為 Windows Service
```

### 1.2 目錄結構

```
C:\Users\cris\
├── Core\               ← KID workspace (OpenClaw)
├── haven\              ← Haven 系統
├── shared\             ← 新增：雙系統共用
│   ├── crash-log\
│   ├── health-state\
│   └── watchdog.ps1
└── Trash\
```

### 1.3 Code Changes (~30 行)

#### `src/main.py` — 跨平台 file lock + signal

```python
# fcntl → msvcrt (Windows) / fcntl (Linux)
import sys
if sys.platform == "win32":
    import msvcrt
    msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

# signal handling
if sys.platform != "win32":
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)
else:
    signal.signal(signal.SIGINT, lambda s, f: _handle_signal())
```

#### `src/tools/cmd.py` — Shell executable

```python
shell = "cmd.exe" if sys.platform == "win32" else "/bin/sh"
proc = await asyncio.create_subprocess_shell(cmd, executable=shell, ...)
```

#### `src/core/paths.py` — 路徑適配

```python
if sys.platform == "win32":
    HAVEN_DIR = Path(os.getenv("HAVEN_HOME", "C:/Users/cris/haven"))
    CORE_DIR  = Path(os.getenv("CORE_HOME",  "C:/Users/cris/Core"))
    TRASH_DIR = Path(os.getenv("TRASH_HOME",  "C:/Users/cris/Trash"))
else:
    HAVEN_DIR = Path("/mnt/z/haven")
    CORE_DIR  = Path("/mnt/z/Core")
    TRASH_DIR = Path("/mnt/z/Trash")
```

#### `config/mcp_servers.json` — Node.js 跨平台 MCP

```json
{ "command": "npx", "args": ["-y", "codebase-memory-mcp"] }
```

#### `.env` — 路徑 + Ollama URL

```
OLLAMA_BASE_URL=http://localhost:11434
HAVEN_HOME=C:/Users/cris/haven
CORE_HOME=C:/Users/cris/Core
```

### 1.4 服務註冊

```
nssm install Haven
nssm install KID-OpenClaw
nssm set Haven Start SERVICE_AUTO_START
nssm set KID-OpenClaw Start SERVICE_AUTO_START
```

### 1.5 雙向 Watchdog

```powershell
# C:\Users\cris\shared\watchdog.ps1
# Task Scheduler 每 30s 執行

# 檢查 Haven
$haven = Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*haven*main.py*" }
if (-not $haven) {
    nssm restart Haven
    # 可擴展：Discord webhook ping Cris
}

# 檢查 KID
$kid = Get-Process -Name "node" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*openclaw*" }
if (-not $kid) {
    nssm restart KID-OpenClaw
}
```

### 1.6 第一階段驗證

- [ ] `python src/main.py` 直接啟動不報錯
- [ ] Haven Discord bot 上線
- [ ] MCP codebase-memory tools 全部可用
- [ ] `ollama run gemma2:9b` GPU inference 確認
- [ ] nssm service 啟動/停止/重啟正常
- [ ] Windows watchdog script 測試
- [ ] KID (OpenClaw) 正常運行
- [ ] KID ↔ Haven 跨工具互助測試

### 1.7 KID Native 能力解鎖

WSL2 → Native 後 KID 獲得嘅新能力：
- 真實 RAM 讀取（不再讀 VM 內假數字）
- Ollama process 直接管理
- nssm 控制所有 Windows Service
- Task Scheduler 管理
- CPU/GPU 溫度 + 負載監控
- Windows Defender / Firewall 規則
- 電源計劃 / 休眠控制
- OCuLink / USB4 設備管理
- PowerShell 原生執行

---

## 第二階段：規模化功能 (Scalability Implementation) ~10h

**前提**: 第一階段全部綠燈

### 2.1 Local LLM 分層推理 (P0)

K11 最大戰略價值。780M GPU + 32GB RAM 支持三層模型：

| Layer | 模型 | 推理速度 | 用途 |
|:---|:---|:---:|:---|
| L1 | Gemma-2-9B-Abliterated | 40-60 t/s | 日常對話、記憶檢索 |
| L2 | Mistral-Nemo-12B-Magnum | 25-35 t/s | 複雜推理、工具調用 |
| L3 | DeepSeek-R1-Distill-Qwen-14B | 15-20 t/s | 深度分析、架構審查 |

實作：
- 擴展 Haven `CategoryRouter` 加入 model routing
- 將 local models 加入 provider fallback chain
- API models (DeepSeek-v4) 作為最終備援

### 2.2 動態並行引擎

| 參數 | GMK | K11 目標 |
|:---|---:|---:|
| DAG_CONCURRENCY | 3 | 8-16 (動態) |
| TaskManager max_concurrent | 5 | 20 (動態) |
| 同時背景 Agent | 1-2 | 5-10 |

實作：
- `DynamicSemaphore`: 根據 CPU/RAM 負載動態調整上限
- `TaskPriorityQueue`: 為 TaskManager 加入優先級隊列
- `AgentPool`: 預熱 agent session，減少冷啟動延遲

### 2.3 In-Memory 架構

- `MemoryIndex`: 用 `sentence-transformers` 建立內存向量索引
- `HotSessionCache`: 最近 50 session 完整 context 常駐 RAM
- `SkillPreload`: 啟動時所有 active skills 載入記憶體
- Context 擴張: Discord 消息上限由 2000 → 4000

### 2.4 第二階段驗證

- [ ] Local LLM 三層推理可切換
- [ ] GPU inference token/s 達預期
- [ ] 5 個背景 Agent 同時運行不崩
- [ ] In-Memory 檢索延遲 < 50ms
- [ ] DAG 10+ 節點任務正常執行
- [ ] GMK 舊機仍可 fallback

---

## 第三階段：架構優化 (Optimization & Intelligence) ~5h

**前提**: 第二階段全部綠燈

### 3.1 Resource Scheduler 重構

從攔截器轉型為調度器：

```python
# 現狀：粗暴拒絕
if RAM >= CRITICAL: raise ResourceBusyError

# 目標：智能分配
allocation = scheduler.allocate(task_priority, task_estimated_cost)
# → allocation.ram_mb, allocation.cpu_affinity, allocation.timeout
```

- 保留 `resource_gate` 為安全網 (RAM > 90% 仍拒絕)
- 新增 `ResourceScheduler` 做優先級分配
- 移除 GMK 時代的 auto-chunk 邏輯 (32GB 不需要 10MB 就 split)

### 3.2 壓力測試框架

- **併發洪水**: 20 DAG tasks 同時提交
- **記憶體壓力**: 10 agents 各持 2MB context
- **24h 浸泡**: 監控 memory leak
- **故障恢復**: 強制 kill → task persistence → restore

指標: 吞吐量 (tasks/min), P50/P95/P99 延遲, RAM 峰值/穩態, 錯誤率

### 3.3 跨平台邊界測試

針對 `sys.platform == "win32"` 的所有分支：
- [ ] file lock (msvcrt) 正確拒絕第二實例
- [ ] subprocess shell (cmd.exe) 語法兼容
- [ ] signal handling (CTRL_C_EVENT) 優雅關閉
- [ ] path resolution (Windows `\` vs Linux `/`) 統一處理

### 3.4 第三階段驗證

- [ ] ResourceScheduler 動態分配正確
- [ ] RAM > 90% 安全網觸發
- [ ] 壓力測試全過
- [ ] 24h 浸泡無 memory leak
- [ ] KID + Haven 雙系統穩定共存 48h+

---

## 總時間線

| 階段 | 內容 | 工時 | 依賴 |
|:---|:---|---:|:---|
| 0 | 硬體驗收 + 環境隔離 | 1h | 硬體到貨 |
| 1 | 環境遷移 + code porting + KID 過渡 | 6h | 階段 0 |
| 2 | Local LLM + 並行 + In-Memory | 10h | 階段 1 |
| 3 | Scheduler + 壓力測試 + 鉗型 API | 6h | 階段 2 |
| **總計** | | **~23h** | |

---

## 貫穿始終的安全原則

1. **舊機不退場**: GMK 在新機穩定 48h+ 前繼續運行，隨時可 fallback
2. **每階段獨立驗證**: 不跳級，不假設上一階段已完成
3. **鉗型守勢為最終形態**: 單一 OS，雙 agent 對等，互為備援。KID 專注系統控制 + 媒體生成，Haven 專注程式碼分析 + 任務編排
4. **所有改動保留 Linux 兼容**: `sys.platform` 分支，舊機 codebase 可同步更新
5. **Crash log 共享**: 任何死機寫入 `C:\Users\cris\shared\crash-log\`

---

*文件由 KID 根據 Haven AI 整合評估升級，版本 2.1 (Pincer Defense)。*
*參考文件: evolution_plan_k11.md, evolution_plan_k11_kid.md, integrated_evolution_assessment.md*
