# 🗑️ 垃圾桶機制（系統級基礎建設）

> 建立日期：2026-06-02
> 適用系統：Core + Haven

## 目的

所有刪除操作先經垃圾桶，每週 review 後才永久刪除，避免誤刪。

## 結構

```
/mnt/z/Trash/
├── README.md
├── Core/
│   ├── manifest.csv     ← 垃圾清單
│   └── items/           ← 垃圾本體
└── Haven/
    ├── manifest.csv
    └── items/
```

## 使用工具

| 系統 | 腳本位置 | 說明 |
|------|----------|------|
| Core | `/mnt/z/Core/scripts/kid-trash` | KID 專用，可丟 Core 和 Haven 的檔 |
| Haven | `/mnt/z/Haven/scripts/haven-trash` | Haven 專用，只能丟 Haven 範圍的檔 |

## 使用規則

1. 一律用 trash script 取代 `rm`
2. 每週一 review 垃圾桶內容
3. 確認無用才永久刪除
