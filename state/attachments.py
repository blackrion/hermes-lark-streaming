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
    - 文本中的 ``MEDIA:`` 前缀标记
    - 文本中的媒体文件路径

    Args:
        source: Hermes 消息数据（dict 或对象），可能包含 attachments/files/media_files.
        text: 消息文本内容，用于扫描 MEDIA: 标记和文件路径.

    Returns:
        附件摘要列表，每项 ``{"type": "image|audio|video|file", "summary": "描述文本"}``.
    """
    summaries: list[dict[str, str]] = []

    # ── 结构化附件对象检测 ──
    if isinstance(source, dict):
        for key in ("attachments", "files", "media_files"):
            items = source.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                summary = _summarize_attachment_item(item)
                if summary:
                    summaries.append(summary)
    elif hasattr(source, "__dict__"):
        for key in ("attachments", "files", "media_files"):
            items = getattr(source, key, None)
            if not isinstance(items, list):
                continue
            for item in items:
                summary = _summarize_attachment_item(item)
                if summary:
                    summaries.append(summary)

    # ── 文本扫描：MEDIA: 标记 ──
    if text:
        for m in _MEDIA_PREFIX_RE.finditer(text):
            summaries.append({"type": "file", "summary": f"📎 {m.group(1).strip()}"})

        # ── 文本扫描：媒体文件路径 ──
        for m in _MEDIA_PATH_RE.finditer(text):
            path = m.group(1)
            ext = m.group(2).lower()
            media_type = _ext_to_media_type(ext)
            emoji = _MEDIA_EMOJI.get(media_type, "📎")
            name = path.rsplit("/", 1)[-1] if "/" in path else path
            summaries.append({"type": media_type, "summary": f"{emoji} {name}"})

    return summaries


def _summarize_attachment_item(item: Any) -> dict[str, str] | None:
    """归纳单个附件对象为摘要."""
    if isinstance(item, str):
        ext = item.rsplit(".", 1)[-1].lower() if "." in item else ""
        media_type = _ext_to_media_type(ext)
        emoji = _MEDIA_EMOJI.get(media_type, "📎")
        name = item.rsplit("/", 1)[-1] if "/" in item else item
        return {"type": media_type, "summary": f"{emoji} {name}"}

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
