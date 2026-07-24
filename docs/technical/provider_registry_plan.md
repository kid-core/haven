# Haven Provider Registry 重構計劃

> 版本: v0.1
> 日期: 2026-07-12
> 狀態: 草案 — 待 Cris 審批
> 作者: KID
> 範圍: src/core/config.py, src/main.py, 新增 config/providers.toml

---

## 一、現狀問題

### 1.1 Provider 資訊分散兩處

而家 Haven 嘅 provider 設定散落喺:

| 資訊 | 位置 | 例子 |
|---|---|---|
| Model name | `.env` (env var) | `HAVEN_PRIMARY_MODEL=deepseek-v4-flash` |
| Base URL | `main.py` (hardcode) | `base_url="https://api.deepseek.com/v1/..."` |
| API key env name | `main.py` (hardcode) | `api_key_env="DEEPSEEK_API_KEY"` |
| Temperature | `main.py` (hardcode) | `default_temperature=0.3` |
| Headers extra | `main.py` (hardcode) | `HTTP-Referer, X-Title` |
| Priority order | `main.py` (list order) | `providers = [(ds,None), (openrouter,None)]` |
| Optional flag | `main.py` (if guard) | `if os.getenv("ARK_API_KEY"):` |

### 1.2 操作成本

加一個新 provider（例如 Claude）需要:
1. 改 `.env` 加 `ANTHROPIC_API_KEY`
2. 改 `main.py` 加 `HttpProvider(...)` 區塊
3. 改 `main.py` 加 `providers.append(...)`
4. 改 `main.py` banner 加 print 行

四步跨兩個檔案，每一步都可能出錯（打錯 env var 名、順序錯、漏 append）。

### 1.3 測試困難

`main.py` 係 entry point，unit test 唔容易直接測 provider 建立邏輯。

---

## 二、目標

- **單一 registry file** 集中管理所有 provider metadata
- **加/減/改 provider 只需改一個 file**（+ `.env` 加 key）
- **不改 code** 即可增刪 provider
- **human-readable**，Cris 可以直覺睇明同手改
- **向後兼容**，`.env` 繼續用，`HavenConfig` 保持不變

---

## 三、設計方案: TOML Registry

### 3.1 選擇 TOML 而非 JSON

| | JSON | TOML |
|---|---|---|
| 註解 | 唔支援 | `# 註解` |
| Trailing comma | 爆 error | 容許 |
| Section 結構 | 要巢狀 object | 自然 `[section]` |
| 人眼可讀 | 大量引號括號 | 簡潔 key=value |
| Python 支援 | `json` (stdlib) | `tomllib` (3.11+ stdlib) |

### 3.2 檔案結構

```toml
# config/providers.toml
# ============================================================
# Haven Provider Registry
# 加/減/改 LLM provider 只需改呢個檔
# API key 照舊放 .env，呢度只寫 env var 名
# ============================================================

[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.openrouter]
name = "OpenRouter"
model_env = "HAVEN_FALLBACK_MODEL"
model_fallback = "google/gemma-4-26b-a4b-it"
base_url = "https://openrouter.ai/api/v1/chat/completions"
api_key_env = "OPENROUTER_API_KEY"
temperature = 0.7
priority = 2
optional = false

[providers.openrouter.headers]
HTTP-Referer = "https://github.com/cris0101_fx/haven"
X-Title = "Haven"

[providers.ds_flash]
name = "DeepSeek Flash"
model_env = "HAVEN_FLASH_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 3
optional = true

[providers.ark]
name = "Ark"
model_env = "HAVEN_TERTIARY_MODEL"
model_fallback = "seed-2-0-lite"
base_url = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
api_key_env = "ARK_API_KEY"
temperature = 0.3
priority = 4
optional = true

# [providers.ollama_vision]       # ← 非 HttpProvider 嘅例子
# type = "ollama"
# name = "Ollama Vision"
# model_fallback = "minicpm-v"
# host = "localhost"
# port = 11434
# category = "vision"
# priority = 5
# optional = true

# [providers.claude]              # ← 未來加 Claude 只需 uncomment
# name = "Claude"
# model_env = "HAVEN_CLAUDE_MODEL"
# model_fallback = "claude-sonnet-4-20250514"
# base_url = "https://api.anthropic.com/v1/messages"
# api_key_env = "ANTHROPIC_API_KEY"
# temperature = 0.5
# priority = 4
# optional = true
```

### 3.3 Field 說明

| Field | 類型 | 說明 |
|---|---|---|
| `name` | string | Provider 顯示名（log/banner 用），可以同 registry key 唔同 |
| `type` | string | Provider 類型：`"http"`（預設）、`"ollama"` |
| `model_env` | string | `.env` 入面 model name 嘅 env var 名 |
| `model_fallback` | string | 如果 env var 冇 set，用呢個 default |
| `base_url` | string | API endpoint URL（`type=http` 必需） |
| `api_key_env` | string | API key 嘅 env var 名 |
| `temperature` | float | Default temperature |
| `priority` | int | 數字越大越優先（fallback 順序） |
| `category` | string | Category tag（e.g. `"vision"`），通用 provider 唔使填 |
| `optional` | bool | `true` = key 唔存在就 skip，唔報錯 |
| `headers` | table | Optional extra HTTP headers（`type=http` 專用） |
| `host` | string | Ollama host（`type=ollama` 專用，default localhost） |
| `port` | int | Ollama port（`type=ollama` 專用，default 11434） |

---

## 四、Code 改動

### 4.1 新增 `src/core/provider_registry.py`

```python
"""Provider registry — load and manage LLM providers from TOML config."""

from __future__ import annotations
import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from core.base_provider import BaseProvider
from core.http_provider import HttpProvider

logger = logging.getLogger(__name__)

# ── provider type → factory ──────────────────────────────────
_PROVIDER_FACTORIES: dict[str, Any] = {}


def _register_factory(type_name: str):
    """Decorator: register a provider factory for a given type string."""
    def decorator(fn):
        _PROVIDER_FACTORIES[type_name] = fn
        return fn
    return decorator


@_register_factory("http")
def _build_http(key: str, cfg: dict) -> HttpProvider:
    return HttpProvider(
        name=cfg.get("name", key),
        model=str(_resolve_model(cfg)),
        base_url=str(cfg["base_url"]),
        api_key_env=str(cfg["api_key_env"]),
        default_temperature=float(cfg.get("temperature", 0.3)),
        headers_extra=cfg.get("headers"),
    )


@_register_factory("ollama")
def _build_ollama(key: str, cfg: dict) -> BaseProvider:
    from tools.ollama_provider import create_ollama_provider
    return create_ollama_provider(
        model=_resolve_model(cfg),
        host=cfg.get("host", "localhost"),
        port=cfg.get("port", 11434),
    )


def _resolve_model(cfg: dict) -> str:
    """Resolve model name: env var > fallback."""
    model_env = cfg.get("model_env", "")
    model_fallback = cfg.get("model_fallback", "")
    if model_env:
        return os.getenv(model_env, model_fallback)
    return model_fallback


# ── Registry ─────────────────────────────────────────────────

class ProviderRegistry:
    """Central registry for LLM providers loaded from TOML config.

    Usage::

        registry = ProviderRegistry.from_toml("config/providers.toml")
        router = Router(registry=registry)

        # lookup
        primary = registry.get("deepseek")
        vision  = registry.by_category("vision")

        # shutdown
        await registry.close_all()
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._meta: dict[str, dict] = {}       # key → raw config
        self._order: list[str] = []             # sorted by priority

    # ── factory ──────────────────────────────────────────

    @classmethod
    def from_toml(cls, path: str | Path) -> ProviderRegistry:
        """Create a ProviderRegistry from a TOML config file."""
        raw = _read_toml(path)
        providers_section = raw.get("providers", {})
        if not providers_section:
            raise RuntimeError(f"No [providers.*] sections found in {path}")

        registry = cls()
        entries: list[tuple[int, str, dict]] = []

        for key, cfg in providers_section.items():
            if not isinstance(cfg, dict):
                continue

            api_key_env = cfg.get("api_key_env", "")
            optional = cfg.get("optional", False)

            # optional + no key → skip silently
            if api_key_env and optional and not os.getenv(api_key_env):
                logger.debug("Skipping optional provider %r (no %s)", key, api_key_env)
                continue

            model_name = _resolve_model(cfg)
            if not model_name and not optional:
                raise ValueError(
                    f"provider '{key}': no model name "
                    f"(env {cfg.get('model_env')} not set, no fallback)"
                )
            if not model_name:
                logger.debug("Skipping optional provider %r (no model)", key)
                continue

            # build provider via type factory
            ptype = cfg.get("type", "http")
            factory = _PROVIDER_FACTORIES.get(ptype)
            if factory is None:
                raise ValueError(
                    f"provider '{key}': unknown type {ptype!r}. "
                    f"Available: {list(_PROVIDER_FACTORIES)}"
                )

            provider = factory(key, cfg)
            priority = cfg.get("priority", 99)
            entries.append((priority, key, cfg))
            registry._providers[key] = provider
            registry._meta[key] = cfg

        entries.sort(key=lambda x: x[0])
        registry._order = [key for _, key, _ in entries]
        return registry

    # ── lookup ───────────────────────────────────────────

    def get(self, name: str) -> BaseProvider | None:
        """Look up a provider by registry key."""
        return self._providers.get(name)

    def primary(self) -> BaseProvider:
        """Return the highest-priority provider."""
        if not self._order:
            raise RuntimeError("No providers loaded")
        return self._providers[self._order[0]]

    def fallback(self, skip: BaseProvider | None = None) -> BaseProvider | None:
        """Return the next available provider after *skip*."""
        start = False
        for key in self._order:
            if skip is not None and self._providers[key] is skip:
                start = True
                continue
            if start or skip is None:
                return self._providers[key]
        return None

    def by_category(self, category: str) -> list[BaseProvider]:
        """Return all providers tagged with *category*."""
        return [
            self._providers[key]
            for key in self._order
            if self._meta.get(key, {}).get("category") == category
        ]

    def to_list(self) -> list[tuple[BaseProvider, str | None]]:
        """Export as (provider, category) list for backward compat with Router."""
        return [
            (self._providers[key], self._meta.get(key, {}).get("category"))
            for key in self._order
        ]

    def __iter__(self):
        return iter(self.to_list())

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, name: str) -> bool:
        return name in self._providers

    # ── lifecycle ────────────────────────────────────────

    async def close_all(self) -> None:
        """Close all managed providers."""
        for key, provider in self._providers.items():
            try:
                await provider.close()
            except Exception:
                logger.exception("Error closing provider %r", key)


# ── helpers ──────────────────────────────────────────────────

def _read_toml(path: str | Path) -> dict:
    """Read TOML file, with helpful error messages."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Provider registry not found: {path}")

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(
            f"Invalid TOML in {path}: {e}\n"
            f"Hint: check for missing quotes, brackets, or invalid syntax."
        ) from e
```

### 4.2 簡化 `src/main.py`

改前（~50 行）:
```python
deepseek = HttpProvider(name="DeepSeek", model=PRIMARY_MODEL,
    base_url="https://api.deepseek.com/v1/chat/completions",
    api_key_env="DEEPSEEK_API_KEY", default_temperature=0.3)
openrouter = HttpProvider(name="OpenRouter", model=FALLBACK_MODEL,
    base_url="https://openrouter.ai/api/v1/chat/completions",
    api_key_env="OPENROUTER_API_KEY", default_temperature=0.7,
    headers_extra={"HTTP-Referer": "...", "X-Title": "Haven"})
ark_provider = None
if os.getenv("ARK_API_KEY"):
    ark_provider = HttpProvider(...)
ds_flash_provider = None
if os.getenv("DEEPSEEK_API_KEY"):
    ds_flash_provider = HttpProvider(...)
providers = [(deepseek,None), (openrouter,None)]
if ds_flash_provider: providers.append(...)
if ark_provider: providers.append(...)
```

改後（5 行）:
```python
from core.provider_registry import ProviderRegistry

registry = ProviderRegistry.from_toml(haven_dir() / "config" / "providers.toml")
providers = list(registry)          # → list[tuple[BaseProvider, str|None]]
logger.info("Loaded %d providers", len(registry))
```

Banner 自動 gen:
```python
for key in registry._order:
    provider = registry.get(key)
    print(f"  {key}: {provider.get_model()}")
```

Router 可直接收 `registry`，取代而家嘅 `providers` list:
```python
# 而家
router = Router(providers=providers, ...)

# 改後
router = Router(registry=registry, ...)
```

### 4.3 `HavenConfig` 不受影響

`HavenConfig` 繼續管理非 provider 設定（heartbeat、transport tokens、feature flags），完全向後兼容。

---

## 五、遷移步驟

### Phase 1: 建立 registry file（唔影響運行）

1. 建立 `config/providers.toml`，內容對應而家 `main.py` 入面 4 個 provider
2. `.env` 唔使改
3. 呢個階段 Haven 照舊用 `main.py` 嘅 hardcode，file 只係擺住

### Phase 2: 實作 `provider_registry.py` + 測試

1. 寫 `src/core/provider_registry.py`
2. 寫 `tests/test_provider_registry.py`:
   - test 正常 load 兩個 provider（http type）
   - test optional provider 被 skip
   - test `type="ollama"` factory 正確建立 OllamaProvider
   - test `by_category("vision")` 正確過濾
   - test `primary()` / `fallback()` 順序正確
   - test `to_list()` 輸出格式兼容現有 Router
   - test missing api_key_env 報錯
   - test TOML 格式錯報 helpful error
   - test priority 排序正確
3. pytest 全 pass

### Phase 3: 改 `main.py` 切換到 registry

1. 將 provider 建立 block 換成 `ProviderRegistry.from_toml()`
2. Router 改收 `registry` 參數（用 `to_list()` 向後兼容）
3. Banner 改用 registry loop gen
4. 移除 `PRIMARY_MODEL` / `FALLBACK_MODEL` / `TERTIARY_MODEL` 呢啲 module-level constants
5. 整合測試確認 Discord/Telegram 正常運作

### Phase 4: Cleanup

1. 確認冇 dead code reference
2. 更新 `CONVENTIONS.txt` 記錄呢個新 pattern

---

## 六、風險評估

| 風險 | 等級 | 緩解 |
|---|---|---|
| TOML 格式寫錯 | 低 | Pydantic/hand-validate + helpful error message |
| 現有 .env 兼容 | 低 | `.env` 完全唔使改，只係多咗一個 toml file |
| 測試覆蓋 | 低 | 新 module 獨立，容易 unit test |
| 部署失敗 | 低 | Phase 1 先放 file 唔影響，Phase 3 先切換 |
| Python 版本 | 無 | `tomllib` 3.11+ stdlib，Haven 行 3.12+ |

---

## 七、加 Claude 嘅例子（將來）

只需兩步，唔使掂 code:

1. `config/providers.toml` 加:
```toml
[providers.claude]
name = "Claude"
model_env = "HAVEN_CLAUDE_MODEL"
model_fallback = "claude-sonnet-4-20250514"
base_url = "https://api.anthropic.com/v1/messages"
api_key_env = "ANTHROPIC_API_KEY"
temperature = 0.5
priority = 5
optional = true

[providers.claude.headers]
anthropic-version = "2023-06-01"
```

2. `.env` 加:
```
HAVEN_CLAUDE_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-***
```

完工。Restart Haven，banner 自動 show Claude。

---

## 八、待 Cris 決定嘅問題

1. **TOML 放邊?** 建議 `config/providers.toml`（同 `mcp_servers.json` 一齊）
2. **model_env 設計?** 每個 provider 獨立 env var（`HAVEN_CLAUDE_MODEL`）定係統一？
3. **priority 方向?** 數字細 = 高優先（default）定係數字大 = 高優先？
4. **立即實作定係先 review?**

---

*本文件保存於 `/mnt/z/haven/docs/technical/provider_registry_plan.md`*
