# 🧪 KID 開發者環境（Haven）

## 為什麼在 Haven？
Haven 是 KID 的開發與實驗區。
Core 是生產線，Haven 是實驗室。

在這裡可以：
- 測試新功能
- 改造 Seed 舊系統
- 跑實驗性腳本
- 不怕弄壞生產環境

## 啟用方式
```bash
source /mnt/z/Core/.venv/bin/activate
```

## 目錄結構
- `/mnt/z/Haven/dev/` — 開發工作區
- `/mnt/z/Haven/quarantine/` — 隔離區
- `/mnt/z/Haven/Soul/` — 靈魂備份
- `/mnt/z/Core/scan.py` — 免疫掃描器（可掃描 Haven 裡的檔案）

## 已安裝套件
requests / python-dotenv / pillow / httpx
