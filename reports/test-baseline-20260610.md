# Haven 測試 Baseline Snapshot

> **日期：** 2026-06-10  
> **環境：** WSL2 / Python 3.12 / dev/kid  
> **命令：** `python -m pytest kid/tests/ -q --tb=short`  
> **結果：** 260 passed, 0 failed, 2 warnings, 13.33s  

## 測試清單（21 files）

| File | Tests | Status |
|------|-------|--------|
| test_heartbeat.py | 8 | ✅ |
| test_http_provider.py | 12 | ✅ |
| test_memory.py | 14 | ✅ |
| test_paths.py | 13 | ✅ |
| test_phase0_policy.py | 8 | ✅ |
| test_phase1_mcp.py | 2 | ✅ |
| test_phase1b_2a.py | 13 | ✅ |
| test_phase3_learning.py | 11 | ✅ |
| test_phase4_spawn.py | 6 | ✅ |
| test_phase6_tasks.py | 14 | ✅ |
| test_phase7_scheduler.py | 11 | ✅ |
| test_phase8_messaging.py | 10 | ✅ |
| test_phase9_persistence.py | 11 | ✅ |
| test_platform.py | 5 | ✅ |
| test_resource_gate.py | 28 | ✅ |
| test_router.py | 16 | ✅ |
| test_search.py | 11 | ✅ |
| test_smoke.py | 22 | ✅ |
| test_spawn_tool.py | 1 | ✅ |
| test_tools.py | 35 | ✅ |
| **Total** | **260** | ✅ |

## CI 指令更新

- `python -m pytest tests/ -m "not slow and not integration" -q --tb=short`

## 備註

- Baseline 作為 Phase 1-6 開始前的 reference point
- 每完成一個 Phase，重新 run 一次確認 regression = 0
