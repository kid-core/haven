# Session 1: Provider Consolidation

## What Changed

Consolidated `DeepSeekProvider` + `OpenRouterProvider` into a single config-driven `HttpProvider`.

### Files

| File | Action | Before (lines) | After (lines) |
|------|--------|---------------|--------------|
| `core/deepseek_provider.py` | Deleted | ~130 | 0 |
| `core/openrouter_provider.py` | Deleted | ~116 | 0 |
| `core/http_provider.py` | Created | 0 | ~80 |
| `core/base_provider.py` | Cleaned | ~50 | ~30 |
| `main.py` | Updated | ~85 | ~85 |
| `tests/test_smoke.py` | Updated | ~56 | ~55 |

**Provider code:** 296 lines → 110 lines (**-63%**, -186 lines)

### Design

`HttpProvider` accepts all differences as constructor kwargs:
- `name` — label for error messages
- `model` — model name string
- `base_url` — API endpoint
- `api_key_env` — env var name for the API key
- `timeout` — HTTP timeout (default 120s)
- `default_temperature` — fallback when None passed (default 0.3)
- `headers_extra` — dict merged into default auth headers (used for OpenRouter Referer/Title)

## Test Results

All 6 tests pass:
- `TestToolRegistry::test_tools_register` ✅
- `TestToolRegistry::test_get_openai_tools_format` ✅
- `TestProviderImports::test_http_provider_imports` ✅
- `TestProviderImports::test_http_provider_config` ✅
- `TestProviderImports::test_base_provider_imports` ✅
- `TestRouter::test_router_imports` ✅

## Boot Test

`timeout 6 python kid/main.py <<< "hello"` — boots, responds, and shuts down gracefully:
```
🏝️  HAVEN — KID Safe Haven
  Primary:   DeepSeek deepseek-v4-flash
  Fallback:  OpenRouter google/gemma-4-26b-a4b-it
  Tools:     ['execute_command', 'write_file', 'read_file']
🏝️ Hello! How can I help you today?
🛑 Haven shut down gracefully.
```
