"""结构化附件/媒体摘要 — 检测 Hermes 消息中的附件并生成卡片摘要.

吸收自 baileyh8/hermes-feishu-streaming-card 的附件摘要能力：
检测图片、音频、视频、文件等结构化附件对象，
在卡片中展示摘要，同时不抑制 Hermes 原生媒体投递路径.
"""

from __future__ import annotations

import re
from typing import Any

# 媒体文件路径正则（文本扫描备用）
_MEDIA_PATH_RE = re.compile(
    r"(?:^|\s)((?:/[\w.-]+)+\.(jpg|jpeg|png|gif|webp|bmp|mp3|wav|m4a|mp4|mov|avi|mkv|pdf|docx?|xlsx?|pptx?|zip|tar|gz))",
    re.IGNORECASE,
)

# MEDIA: 前缀标记
_MEDIA_PREFIX_RE = re.compile(r"^MEDIA:\s*(.+)$", re.MULTILINE)

_MEDIA_EMOJI = {
    "image": "🖼️",
    "audio": "🎵",
    "video": "🎬",
    "file": "📎",
}


def extract_attachment_summaries(
    source: Any,
    *,
    text: str = "",
) -> list[dict[str, str]]:
    """从 Hermes 消息数据中提取附件摘要.

    检测多种 Hermes 附件格式：
    - ``attachments`` 列表（结构化对象）
    - ``files`` 列表
    - ``media_files`` 列表
    - ``media_urls`` / ``media_types``（Hermes ``MessageEvent`` 的本地媒体缓存）
    - 文本中的 ``MEDIA:`` 前缀标记
    - 文本中的媒体文件路径

    Args:
        source: Hermes 消息数据（dict 或对象），可能包含 attachments/files/media_files/media_urls.
        text: 消息文本内容，用于扫描 MEDIA: 标记和文件路径.

    Returns:
        附件摘要列表，每项 ``{"type": "image|audio|video|file", "summary": "描述文本"}``.
    """
    summaries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_summary(summary: dict[str, str] | None) -> None:
        if not summary:
            return
        key = f"{summary.get('type', '')}\0{summary.get('summary', '')}"
        if key in seen:
            return
        seen.add(key)
        summaries.append(summary)

    # ── 结构化附件对象检测 ──
    if isinstance(source, dict):
        for key in ("attachments", "files", "media_files"):
            items = source.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                add_summary(_summarize_attachment_item(item))
        media_urls = source.get("media_urls")
        media_types = source.get("media_types")
        for summary in _summarize_media_urls(media_urls, media_types):
            add_summary(summary)
    elif hasattr(source, "__dict__"):
        for key in ("attachments", "files", "media_files"):
            items = getattr(source, key, None)
            if not isinstance(items, list):
                continue
            for item in items:
                add_summary(_summarize_attachment_item(item))
        media_urls = getattr(source, "media_urls", None)
        media_types = getattr(source, "media_types", None)
        for summary in _summarize_media_urls(media_urls, media_types):
            add_summary(summary)

    # ── 文本扫描：MEDIA: 标记 ──
    if text:
        for m in _MEDIA_PREFIX_RE.finditer(text):
            add_summary(_summarize_media_entry(m.group(1).strip(), ""))

        # ── 文本扫描：媒体文件路径 ──
        for m in _MEDIA_PATH_RE.finditer(text):
            path = m.group(1)
            ext = m.group(2).lower()
            media_type = _ext_to_media_type(ext)
            emoji = _MEDIA_EMOJI.get(media_type, "📎")
            name = path.rsplit("/", 1)[-1] if "/" in path else path
            add_summary({"type": media_type, "summary": f"{emoji} {name}"})

    return summaries


def _summarize_attachment_item(item: Any) -> dict[str, str] | None:
    """归纳单个附件对象为摘要."""
    if isinstance(item, str):
        return _summarize_media_entry(item, "")

    if isinstance(item, dict):
        # 尝试提取类型和名称
        media_type = "file"
        for type_key in ("type", "media_type", "kind"):
            val = item.get(type_key, "")
            if val and isinstance(val, str):
                if "image" in val or "img" in val:
                    media_type = "image"
                elif "audio" in val:
                    media_type = "audio"
                elif "video" in val:
                    media_type = "video"
                break

        # 尝试提取名称
        name = ""
        for name_key in ("name", "filename", "file_name", "title", "path", "url"):
            val = item.get(name_key, "")
            if val and isinstance(val, str):
                name = val.rsplit("/", 1)[-1] if "/" in val else val
                break

        emoji = _MEDIA_EMOJI.get(media_type, "📎")
        if name:
            return {"type": media_type, "summary": f"{emoji} {name}"}
        return {"type": media_type, "summary": f"{emoji} {media_type.title()}"}

    return None


def _summarize_media_urls(
    media_urls: Any,
    media_types: Any,
) -> list[dict[str, str]]:
    """归纳 Hermes MessageEvent.media_urls/media_types 为附件摘要."""
    if not isinstance(media_urls, list):
        return []
    type_list = media_types if isinstance(media_types, list) else []
    summaries: list[dict[str, str]] = []
    for index, media_url in enumerate(media_urls):
        summary = _summarize_media_entry(
            media_url,
            type_list[index] if index < len(type_list) else "",
        )
        if summary:
            summaries.append(summary)
    return summaries


def _summarize_media_entry(path_or_url: Any, media_type_hint: Any = "") -> dict[str, str] | None:
    """归纳本地媒体路径/URL 为摘要."""
    if not isinstance(path_or_url, str) or not path_or_url.strip():
        return None
    raw = path_or_url.strip()
    name = raw.rsplit("/", 1)[-1] if "/" in raw else raw
    media_type = _normalize_media_type(media_type_hint, fallback_name=name)
    emoji = _MEDIA_EMOJI.get(media_type, "📎")
    return {"type": media_type, "summary": f"{emoji} {name}"}


def _normalize_media_type(media_type_hint: Any, *, fallback_name: str = "") -> str:
    """标准化 Hermes/Feishu 媒体类型提示."""
    value = str(media_type_hint or "").lower()
    if "image" in value or "photo" in value or "img" in value:
        return "image"
    if "audio" in value or "voice" in value:
        return "audio"
    if "video" in value:
        return "video"
    if "document" in value or "file" in value or "application" in value:
        return "file"
    ext = fallback_name.rsplit(".", 1)[-1].lower() if "." in fallback_name else ""
    return _ext_to_media_type(ext)


def _ext_to_media_type(ext: str) -> str:
    """文件扩展名 → 媒体类型."""
    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "ico"}
    audio_exts = {"mp3", "wav", "m4a", "flac", "ogg", "aac", "wma"}
    video_exts = {"mp4", "mov", "avi", "mkv", "webm", "flv", "wmv"}
    if ext in image_exts:
        return "image"
    if ext in audio_exts:
        return "audio"
    if ext in video_exts:
        return "video"
    return "file"


def build_attachment_summary_elements(
    summaries: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """将附件摘要列表转换为 Card 2.0 元素列表.

    生成一个简洁的 div 元素，每行一个附件摘要.
    """
    if not summaries:
        return []

    lines = "\n".join(s["summary"] for s in summaries[:10])  # 最多展示10个
    if len(summaries) > 10:
        lines += f"\n... 及其他 {len(summaries) - 10} 个附件"

    return [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": lines,
            },
        }
    ]


__all__ = [
    "extract_attachment_summaries",
    "build_attachment_summary_elements",
]
