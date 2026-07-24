#!/usr/bin/env python3
"""
Tool Output Contract — 統一的工具輸出包裝層

強制所有工具回傳符合 ToolOutput schema 的 dict，確保 LLM 能精確判斷
工具是否成功執行，避免幻覺（如「已發送檔案」但實際上傳失敗）。

核心組件：
- ToolErrorCode   — 標準化錯誤碼枚舉
- ToolOutput      — Pydantic v2 輸出模型
- wrap_output()   — 工廠函式，手動建立合規輸出
- @tool_output     — 裝飾器，自動包裝工具 execute() 方法
"""

from __future__ import annotations

import time
from enum import Enum
from functools import wraps
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── 錯誤碼 ──────────────────────────────────────

class ToolErrorCode(str, Enum):
    """標準化工具錯誤碼。

    LLM 可依 code 判斷是否應重試或回報使用者。
    """
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    API_ERROR = "API_ERROR"
    TIMEOUT = "TIMEOUT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_PARAMS = "INVALID_PARAMS"
    UNKNOWN = "UNKNOWN"


# ── Pydantic 模型 ───────────────────────────────

class ToolError(BaseModel):
    """工具錯誤資訊。"""
    code: str
    message: str
    retryable: bool = False


class ToolMeta(BaseModel):
    """工具執行詮釋資料。"""
    exec_ms: int = Field(ge=0, description="執行時間（毫秒）")
    truncated: bool = False


class ToolOutput(BaseModel):
    """統一的工具輸出合約。

    Attributes
    ----------
    status : Literal["success", "failure", "partial"]
        執行狀態
    data : Any | None
        工具的回傳資料（成功時為實際結果，失敗時可為 None）
    error : ToolError | None
        錯誤資訊（成功時為 None）
    meta : ToolMeta
        執行詮釋資料
    """
    status: Literal["success", "failure", "partial"]
    data: Any = None
    error: Optional[ToolError] = None
    meta: Optional[ToolMeta] = None

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_failure(self) -> bool:
        return self.status == "failure"


# ── 工廠函式 ────────────────────────────────────

def wrap_output(
    status: str,
    data: Any = None,
    error: Optional[dict] = None,
    exec_ms: Optional[int] = None,
    truncated: bool = False,
) -> dict:
    """建立符合 ToolOutput 合約的 dict。

    Parameters
    ----------
    status : str
        "success" | "failure" | "partial"
    data : Any, optional
        成功時的資料內容。
    error : dict, optional
        錯誤資訊 dict，含 code / message / retryable。
    exec_ms : int, optional
        執行時間（毫秒），若為 None 則設為 0。
    truncated : bool
        資料是否被截斷。

    Returns
    -------
    dict
        合規的輸出 dict：{"status", "data", "error", "meta"}
    """
    return {
        "status": status,
        "data": data,
        "error": error,
        "meta": {
            "exec_ms": exec_ms if exec_ms is not None else 0,
            "truncated": truncated,
        },
    }


# ── 內部輔助 ────────────────────────────────────

def _classify_error_message(msg: str) -> tuple[ToolErrorCode, bool]:
    """從錯誤訊息文字推斷錯誤碼與是否可重試。"""
    lower = str(msg).lower()
    if "file not found" in lower or "not a file" in lower:
        return ToolErrorCode.FILE_NOT_FOUND, False
    if "file too large" in lower or "too large" in lower:
        return ToolErrorCode.FILE_TOO_LARGE, False
    if lower.startswith("missing"):
        return ToolErrorCode.INVALID_PARAMS, False
    if "smtp" in lower:
        return ToolErrorCode.API_ERROR, True
    if "timeout" in lower:
        return ToolErrorCode.TIMEOUT, True
    if "permission" in lower or "denied" in lower:
        return ToolErrorCode.PERMISSION_DENIED, False
    return ToolErrorCode.UNKNOWN, True


def _classify_exception(exc: Exception) -> tuple[ToolErrorCode, bool]:
    """從例外推斷錯誤碼。"""
    if isinstance(exc, FileNotFoundError):
        return ToolErrorCode.FILE_NOT_FOUND, False
    if isinstance(exc, PermissionError):
        return ToolErrorCode.PERMISSION_DENIED, False
    return _classify_error_message(str(exc))


def _convert_legacy(result: dict, elapsed_ms: int) -> dict:
    """將舊式 {"success": bool, "result": str, ...} 轉為新式合約。

    額外欄位（action, path, filename, to, subject 等）保留在頂層，
    以供下游消費者（如 haven_discord.py）直接存取。
    """
    success = result.get("success", False)
    status = "success" if success else "failure"
    data_value = result.get("result")

    output: dict[str, Any] = {
        "status": status,
        "data": data_value,
        "error": None,
        "meta": {"exec_ms": elapsed_ms, "truncated": False},
    }

    if not success:
        msg = str(result.get("result", "Unknown error"))
        code, retryable = _classify_error_message(msg)
        output["error"] = {
            "code": code.value,
            "message": msg,
            "retryable": retryable,
        }

    # 保留舊格式中的所有額外欄位（合約鍵以外的全部透傳）
    _contract_keys = {"success", "result"}
    for key, value in result.items():
        if key not in _contract_keys and key not in output:
            output[key] = value

    return output


# ── 裝飾器 ──────────────────────────────────────

def tool_output(func):
    """裝飾器：自動包裝工具 execute() 方法的輸出為 ToolOutput 合約。

    功能：
    1. 計時（exec_ms）
    2. 若回傳值已有 "status" 鍵，僅補 meta
    3. 若為舊式 {"success": bool, "result": str}，自動轉換
    4. 捕捉所有例外並格式化為 error 欄位

    Usage
    -----
    class MyTool(BaseTool):
        @tool_output
        def execute(self, **kwargs) -> dict:
            ...
    """
    @wraps(func)
    def wrapper(self, **kwargs):
        start = time.monotonic_ns()
        try:
            result = func(self, **kwargs)
            elapsed_ms = (time.monotonic_ns() - start) // 1_000_000

            if not isinstance(result, dict):
                return wrap_output("success", data=result, exec_ms=elapsed_ms)

            # 已是新格式：補 meta
            if "status" in result:
                if result.get("meta") is None:
                    result["meta"] = {"exec_ms": elapsed_ms, "truncated": False}
                elif isinstance(result["meta"], dict) and "exec_ms" not in result["meta"]:
                    result["meta"]["exec_ms"] = elapsed_ms
                return result

            # 舊式格式：{"success": bool, "result": str, ...} → 轉換
            if "success" in result:
                return _convert_legacy(result, elapsed_ms)

            # 未識別格式：包裝為成功
            return wrap_output("success", data=result, exec_ms=elapsed_ms)

        except Exception as exc:
            elapsed_ms = (time.monotonic_ns() - start) // 1_000_000
            code, retryable = _classify_exception(exc)
            return wrap_output(
                "failure",
                error={
                    "code": code.value,
                    "message": str(exc),
                    "retryable": retryable,
                },
                exec_ms=elapsed_ms,
            )

    return wrapper
