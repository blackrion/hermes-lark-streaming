"""工具调用追踪与可视化 — 与 openclaw-lark 工具展示对齐."""

from __future__ import annotations

__all__ = [
    "ToolStep",
    "ToolSession",
    "ToolUseTracker",
    "redact_inline_secrets",
    "_basename_only",
    "_build_display_block",
    "_fenced_block",
    "_format_duration_label",
    "_humanize_tool_name",
    "_redact_paths",
    "_resolve_tool_descriptor",
    "_sanitize_detail",
    "_TOOL_DESCRIPTORS",
    "_SENSITIVE_NAME_RE",
    "_INLINE_ASSIGNMENT_RE",
    "_AUTH_HEADER_RE",
    "_SECRET_FLAG_RE",
]

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolStep:
    name: str
    status: str  # running | success | error
    detail: str = ""
    output: str = ""
    error: str = ""
    result_block: dict[str, Any] | None = None  # {"language": "json"|"text", "content": str}
    error_block: dict[str, Any] | None = None
    started_at: float = 0.0
    elapsed_ms: float = 0.0


@dataclass
class ToolSession:
    steps: list[ToolStep] = field(default_factory=list)
    started_at: float = 0.0


_SENSITIVE_NAME_RE = re.compile(
    r"token|secret|password|api[_-]?key|authorization|cookie|credential"
    r"|bearer|session[_-]?id|client[_-]?secret|access[_-]?key",
    re.IGNORECASE,
)

_INLINE_ASSIGNMENT_RE = re.compile(r'(^|[\s"\'`])([A-Za-z_][A-Za-z0-9_]*)(=(?:"[^"]*"|\'[^\']*\'|[^\s"\'`]+))')
_AUTH_HEADER_RE = re.compile(
    r"(Authorization\s*:\s*(?:Bearer|Basic|Token)\s+)([^\'\"\s]+)",
    re.IGNORECASE,
)
_SECRET_FLAG_RE = re.compile(
    r'((?:^|[\s"\'`])(--?[A-Za-z0-9][A-Za-z0-9-]*)(=|\s+)("(?:[^"]*)"|\'(?:[^\']*)\'|[^\s"\'`]+))'
)
# -H / --header flag with sensitive header name (e.g. -H "Authorization: Bearer xxx")
_HEADER_FLAG_RE = re.compile(
    r'(-H\s+|--header\s+)(["\'])(.*?)(["\'])',
    re.IGNORECASE | re.DOTALL,
)


def redact_inline_secrets(value: str) -> str:
    """脱敏 key=secret、Authorization header、--flag secret、-H header 模式.

    Ported and enhanced from openclaw-lark ``redactInlineSecrets()`` (MIT, ByteDance).
    """

    def _redact_assign(m: re.Match) -> str:
        key = str(m.group(2))
        if _SENSITIVE_NAME_RE.search(key):
            return f"{m.group(1)}{key}=[redacted]"
        return str(m.group(0))

    def _redact_flag(m: re.Match) -> str:
        flag = re.sub(r"^-+", "", str(m.group(2)))
        if _SENSITIVE_NAME_RE.search(flag):
            return f"{m.group(1)}{m.group(2)}{m.group(3)}[redacted]"
        return str(m.group(0))

    def _redact_header_flag(m: re.Match) -> str:
        flag_prefix, open_q, content, close_q = m.groups()
        colon_idx = content.find(":")
        if colon_idx > 0:
            header_name = content[:colon_idx].strip()
            if _SENSITIVE_NAME_RE.search(header_name):
                redacted = content[:colon_idx + 1] + " [redacted]"
                return f"{flag_prefix}{open_q}{redacted}{close_q}"
        return str(m.group(0))

    return _HEADER_FLAG_RE.sub(
        _redact_header_flag,
        _SECRET_FLAG_RE.sub(
            _redact_flag,
            _AUTH_HEADER_RE.sub(r"\1[redacted]", _INLINE_ASSIGNMENT_RE.sub(_redact_assign, value)),
        ),
    )


def _sanitize_detail(text: str, sanitizer: str | None) -> str:
    """根据 sanitizer 类型清洗 detail 文本.

    Ported from openclaw-lark ``sanitizeToolDetail()`` (MIT, ByteDance).
    """
    if not text or not sanitizer:
        return text
    cleaned = re.sub(r"<[^>]+>", "", text).strip()
    if not cleaned:
        return text
    if sanitizer == "command":
        return _sanitize_command_like(cleaned)
    if sanitizer == "path":
        return _sanitize_path_like(cleaned)
    if sanitizer == "search":
        return _strip_quotes(cleaned)
    if sanitizer == "url":
        result = _strip_quotes(cleaned)
        return re.sub(r"^from\s+", "", result, flags=re.IGNORECASE)
    if sanitizer == "skill":
        result = re.sub(r"^skill\s+", "", cleaned, flags=re.IGNORECASE)
        result = re.sub(r"[-_]+", " ", result).strip()
        return result or "skill"
    return cleaned


def _redact_paths(text: str) -> str:
    """命令中路径只保留 basename（向后兼容保留）."""
    return re.sub(
        r'(^|[\s=\'"()])([~./][^\s\'"()]+)',
        lambda m: f"{m.group(1)}{os.path.basename(m.group(2))}",
        text,
    )


def _basename_only(text: str) -> str:
    if not text:
        return text
    return os.path.basename(text.replace("\\", "/").rstrip("/"))


# ---------------------------------------------------------------------------
# Ported from openclaw-lark (MIT, ByteDance)
# ---------------------------------------------------------------------------

def _strip_quotes(value: str) -> str:
    """Strip leading/trailing quotes and backticks."""
    return re.sub(r"^[`'\"]+|[`'\"]+$", "", value).strip()


def _sanitize_url_for_display(url: str) -> str:
    """Strip credentials and sensitive query params from URL."""
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    try:
        parsed = urlparse(url)
        parsed = parsed._replace(username="", password="")
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            for key in list(params):
                if _SENSITIVE_NAME_RE.search(key):
                    params[key] = ["[redacted]"]
            parsed = parsed._replace(query=urlencode(params, doseq=True))
        return urlunparse(parsed)
    except Exception:
        return url


def _looks_like_path(value: str) -> bool:
    return (
        value.startswith("~/")
        or value.startswith("./")
        or value.startswith("../")
        or value.startswith("/")
        or "/" in value
    )


def _basename_from_path(value: str) -> str:
    cleaned = value.replace("\\", "/").rstrip("/")
    segments = [s for s in cleaned.split("/") if s]
    return segments[-1] if segments else value


def _redact_standalone_path(value: str) -> str:
    """Redact a standalone path token to basename, preserving URLs."""
    if re.match(r"^https?://", value, re.IGNORECASE):
        return _sanitize_url_for_display(value)
    if not _looks_like_path(value):
        return value
    return _basename_from_path(value)


def _redact_command_paths(command: str) -> str:
    """Redact paths in command tokens, preserving structure."""
    def _redact_token(token: str) -> str:
        if not token or token.isspace():
            return token
        match = re.match(r'^([("\'`]*)(.*?)([)"\'`,;:]*)$', token)
        if not match:
            return token
        prefix, core, suffix = match.groups()
        eq_idx = core.find("=")
        if eq_idx > 0:
            left = core[:eq_idx + 1]
            right = core[eq_idx + 1:]
            return f"{prefix}{left}{_redact_standalone_path(right)}{suffix}"
        return f"{prefix}{_redact_standalone_path(core)}{suffix}"

    return "".join(_redact_token(t) for t in re.split(r"(\s+)", command))


def _sanitize_command_like(value: str, *, show_full_paths: bool = False) -> str:
    """Strip command prefixes, redact secrets, and redact paths.

    Ported from openclaw-lark ``sanitizeCommandLike()`` (MIT, ByteDance).
    """
    cleaned = _strip_quotes(value)
    cleaned = re.sub(r"^(?:command|script|description)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^.*?\s+->\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    if not cleaned:
        return "command"
    redacted = redact_inline_secrets(cleaned)
    if show_full_paths:
        return redacted
    return _redact_command_paths(redacted)


def _sanitize_path_like(value: str, *, show_full_paths: bool = False) -> str:
    """Strip path prefixes, detect skill paths, return basename.

    Ported from openclaw-lark ``sanitizePathLike()`` (MIT, ByteDance).
    """
    cleaned = re.sub(r"<[^>]+>", "", value).strip()
    cleaned = re.sub(r"^(?:from|file|path)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    if show_full_paths:
        return cleaned
    # Check for skill path: skills/skill-name/
    skill_match = re.search(r"(?:^|/)skills/([^/]+)/", cleaned, re.IGNORECASE)
    if skill_match:
        skill_name = skill_match.group(1).replace("-", " ").replace("_", " ").strip()
        return skill_name or cleaned
    # Return basename only
    segments = [s for s in re.split(r"[\\/]", cleaned) if s]
    return segments[-1] if segments else cleaned


_TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {"aliases": ["skill"], "icon": "app-default_outlined", "title": "Load skill", "sanitizer": None},
    {
        "aliases": ["read", "open"],
        "icon": "file-link-text_outlined",
        "title": "Read",
        "sanitizer": "path",
        "no_result": True,
    },
    {
        "aliases": ["write", "edit"],
        "icon": "edit_outlined",
        "title": "Edit",
        "sanitizer": "path",
        "no_result": True,
    },
    {
        "aliases": ["web_search", "web-search", "search"],
        "icon": "search_outlined",
        "title": "Search",
        "sanitizer": "search",
    },
    {
        "aliases": ["web_fetch", "web-fetch", "fetch"],
        "icon": "language_outlined",
        "title": "Fetch web page",
        "sanitizer": "url",
        "no_result": True,
    },
    {"aliases": ["grep"], "icon": "doc-search_outlined", "title": "Search text", "sanitizer": "search"},
    {"aliases": ["glob"], "icon": "folder_outlined", "title": "Search files", "sanitizer": "path"},
    {
        "aliases": ["exec", "bash", "command", "run"],
        "icon": "setting_outlined",
        "title": "Run command",
        "sanitizer": "command",
    },
    {
        "aliases": ["browser", "playwright", "navigate"],
        "icon": "browser-mac_outlined",
        "title": "Browser",
        "no_result": True,
    },
    {"aliases": ["agent", "task", "spawn"], "icon": "robot_outlined", "title": "Run sub-agent"},
    {"aliases": ["check", "determine", "verify"], "icon": "list-check_outlined", "title": "Check"},
    {"aliases": ["summarize", "analyze", "prepare"], "icon": "report_outlined", "title": "Analyze"},
]


def _resolve_tool_descriptor(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    normalized = name.strip().lower().replace("-", "_")
    for desc in _TOOL_DESCRIPTORS:
        for alias in desc["aliases"]:
            if normalized == alias or normalized.startswith(f"{alias}_"):
                return desc
    return None


def _humanize_tool_name(name: str) -> str:
    cleaned = name.replace("-", " ").replace("_", " ").strip()
    if not cleaned:
        return "Tool"
    return cleaned[0].upper() + cleaned[1:]


def _format_duration_label(ms: float) -> str:
    return f"{ms:.0f} ms" if ms < 1000 else f"{(ms / 1000):.1f} s"


def _build_display_block(
    value: Any,
    fallback_lang: str = "json",
    *,
    sanitizer: str | None = None,
) -> dict[str, Any] | None:
    """构建结果/错误的显示块 — 返回 {language, content, fenced} 含 markdown 代码围栏."""
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.replace("\r\n", "\n").strip()
        if not normalized:
            return None
        if sanitizer == "command":
            normalized = redact_inline_secrets(normalized)
        if normalized.startswith("{") or normalized.startswith("["):
            try:
                parsed = json.loads(normalized)
                pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
                return _fenced_block("json", pretty)
            except json.JSONDecodeError:
                pass
        return _fenced_block("text" if fallback_lang == "json" else fallback_lang, normalized)
    if isinstance(value, (dict, list)):
        try:
            return _fenced_block("json", json.dumps(value, ensure_ascii=False, indent=2))
        except (TypeError, ValueError):
            pass
    normalized = str(value).strip()
    return _fenced_block("text", normalized) if normalized else None


def _fenced_block(language: str, content: str) -> dict[str, Any]:
    fence = "`" * max(3, max((len(m) for m in re.findall(r"`+", content)), default=0) + 1)
    return {"language": language, "content": content, "fenced": f"{fence}{language}\n{content}\n{fence}"}


class ToolUseTracker:
    """追踪当前消息中的工具调用步骤.

    按 session 隔离，每个会话独立生命周期.
    """

    def __init__(self, max_steps: int = 128) -> None:
        self._session: ToolSession | None = None
        self._max_steps = max_steps

    @property
    def elapsed_ms(self) -> float:
        if self._session is None:
            return 0.0
        return (time.time() - self._session.started_at) * 1000

    def record_start(self, name: str, detail: str = "") -> None:
        if self._session is None:
            self._session = ToolSession(started_at=time.time())
        if len(self._session.steps) >= self._max_steps:
            return
        self._session.steps.append(
            ToolStep(
                name=name,
                status="running",
                detail=detail,
                started_at=time.time(),
            )
        )

    def record_end(self, name: str, *, error: str = "", output: str = "") -> None:
        """通过名字匹配最近的一个 running 步骤来结束."""
        if self._session is None:
            return
        desc = _resolve_tool_descriptor(name)
        sanitizer = desc.get("sanitizer") if desc else None
        for step in reversed(self._session.steps):
            if step.name == name and step.status == "running":
                step.status = "error" if error else "success"
                step.error = error
                step.output = output
                step.elapsed_ms = (time.time() - step.started_at) * 1000
                if error:
                    step.error_block = _build_display_block(error, "text", sanitizer=sanitizer)
                elif output:
                    step.result_block = _build_display_block(output, "json", sanitizer=sanitizer)
                return
        self._session.steps.append(
            ToolStep(
                name=name,
                status="error" if error else "success",
                detail=error or output,
                output=output,
                error=error,
                started_at=time.time(),
                error_block=_build_display_block(error, "text", sanitizer=sanitizer) if error else None,
                result_block=_build_display_block(output, "json", sanitizer=sanitizer) if output else None,
            )
        )

    def build_display_steps(self) -> list[dict[str, Any]]:
        """构建用于卡片渲染的步骤列表 — 与 openclaw 结构对齐."""
        if self._session is None:
            return []
        steps = []
        for s in self._session.steps:
            desc = _resolve_tool_descriptor(s.name)
            base_title = desc["title"] if desc else _humanize_tool_name(s.name)
            if s.elapsed_ms > 0:
                base_title = f"{base_title} ({_format_duration_label(s.elapsed_ms)})"
            sanitizer = desc.get("sanitizer") if desc else None
            detail = _sanitize_detail(s.detail, sanitizer)
            steps.append(
                {
                    "name": s.name,
                    "title": base_title,
                    "status": s.status,
                    "detail": detail,
                    "output": s.output,
                    "error": s.error,
                    "icon": desc["icon"] if desc else "setting-inter_outlined",
                    "elapsed_ms": s.elapsed_ms,
                    "result_block": None if (desc and desc.get("no_result")) else s.result_block,
                    "error_block": s.error_block,
                }
            )
        return steps
