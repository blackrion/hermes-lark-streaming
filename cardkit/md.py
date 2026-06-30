"""Markdown 文本处理 — 标题降级、表格降级、图片 key 剥离、长文本分块."""

from __future__ import annotations

import logging
import re

_logger = logging.getLogger("hermes_lark_streaming")

_MAX_CARD_TABLES = 20  # 流式卡片：20表降级阈值（流式增量内容，飞书宽松执行）
_MAX_CRON_TABLES = 5   # 静态卡片：5表降级阈值（飞书 Card 2.0 单卡硬限）
_MAX_CHUNK_CHARS = 2400

__all__ = [
    "_MAX_CRON_TABLES",
    "_downgrade_tables",
    "_find_tables_outside_code_blocks",
    "_split_long_text",
    "_strip_invalid_image_keys",
    "escape_markdown_asterisks",
    "optimize_markdown_style",
]


def _find_tables_outside_code_blocks(text: str) -> list[tuple[int, int, str]]:
    """查找代码块外的 markdown 表格，返回 [(start, end, raw), ...]."""
    code_ranges: list[tuple[int, int]] = []
    for m in re.finditer(r"```[\s\S]*?```", text):
        code_ranges.append((m.start(), m.end()))

    def _in_code(idx: int) -> bool:
        return any(s <= idx < e for s, e in code_ranges)

    results: list[tuple[int, int, str]] = []
    for m in re.finditer(r"\|.+\|\n\|[-:| ]+\|[\s\S]*?(?=\n\n|\n(?!\|)|$)", text):
        if not _in_code(m.start()):
            results.append((m.start(), m.end(), m.group(0)))
    return results


def _downgrade_tables(text: str, limit: int = _MAX_CARD_TABLES) -> str:
    """超限表格降级为代码块（保留内容可见但飞书不渲染为表格元素）."""
    # Early return: no tables possible without pipe characters
    if '|' not in text:
        return text
    matches = _find_tables_outside_code_blocks(text)
    if len(matches) <= limit:
        return text
    result = text
    for start, end, raw in reversed(matches[limit:]):
        replacement = f"```\n{raw}\n```"
        result = result[:start] + replacement + result[end:]
    return result


def _strip_invalid_image_keys(text: str) -> str:
    """移除非 img_ 前缀的图片引用."""
    if "![" not in text:
        return text

    def _replace(m: re.Match) -> str:
        return m.group(0) if m.group(2).startswith("img_") else ""

    return re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", _replace, text)


def escape_markdown_asterisks(text: str) -> str:
    """保护合法 Markdown 强调结构，转义所有剩余 *。

    飞书 Markdown 解析器比 CommonMark 更激进——会把 2*4000+4*3000
    中的 *4000+4* 配对为斜体，导致乘号消失、数字拼合。

    解决思路：先保护合法 Markdown 结构（粗体、斜体、代码），再转义一切剩余 *。

    算法：
    1. 提取代码块/行内代码 → 保护（代码内 * 是字面量）
    2. 提取粗体 **...** → 保护（粗体永远是排版意图）
    3. 提取合法斜体 *...* → 保护（开头*不在ASCII字母/数字/下划线后）
    4. 转义所有剩余 *（飞书可能误配对的）
    5. 还原保护区域
    """
    if '*' not in text:
        return text

    _protected: list[str] = []

    def _save(m: re.Match) -> str:
        _protected.append(m.group(0))
        return f'\x00P{len(_protected) - 1}P\x00'

    # Step 1: 保护代码区域
    text = re.sub(r'```[\s\S]*?```', _save, text)
    text = re.sub(r'`[^`]+`', _save, text)

    # Step 2: 保护粗体 **...** 和 ***...***
    text = re.sub(
        r'\*{2,3}(?!\s)((?:(?!\*{2,3}).)+?)(?<!\s)\*{2,3}',
        _save, text, flags=re.DOTALL,
    )

    # Step 3: 保护合法斜体 *...*
    # 开头 * 合法条件：前面不是 ASCII 字母/数字/下划线
    text = re.sub(
        r'(?<![a-zA-Z0-9_])\*(?!\s)((?:(?!\*).)+?)(?<!\s)\*',
        _save, text, flags=re.DOTALL,
    )

    # Step 4: 转义剩余 *
    text = re.sub(r'(?<!\\)\*(?=[^\s*])', r'\\*', text)

    # Step 5: 还原保护区域 (v1.3.0 perf: O(N) single regex sub)
    if _protected:
        text = re.sub(
            r'\x00P(\d+)P\x00',
            lambda m: _protected[int(m.group(1))], text
        )

    return text


def optimize_markdown_style(text: str) -> str:
    """优化流式 Markdown 以适配飞书 CardKit 渲染.

    Ported from openclaw-lark ``optimizeMarkdownStyle()`` (MIT, ByteDance).

    1. 提取代码块用占位符保护
    2. 标题降级: H1 -> H4, H2-H6 -> H5
    3. 连续标题间增加段落间距 (``<br>``)
    4. 表格前后增加段落间距 (``<br>``)
    5. 还原代码块并在前后追加 ``<br>``
    6. 压缩多余空行
    7. 剥离无效图片 key（非 img_xxx 格式）
    """
    # Early return: short texts without markdown structure don't need
    # complex regex processing.  Skip only when no headings, code blocks,
    # images, tables, or excessive blank lines are present.
    if len(text) < 100 and not re.search(r'^#{1,6} |\n#{1,6} |```|!\[|\n{3,}|\|.*\|', text):
        return text
    try:
        # 1. 提取代码块
        mark = "___CB_"
        code_blocks: list[str] = []

        def _extract(m: re.Match) -> str:
            prefix = m.group(1) or ""
            block = m.group(0)[len(prefix) :]
            idx = len(code_blocks)
            code_blocks.append(block)
            return f"{prefix}{mark}{idx}___"

        r = re.sub(r"(^|\n)(`{3,})([^\n]*)\n[\s\S]*?\n\2(?=\n|$)", _extract, text)

        # 2. 标题降级（仅当存在 H1-H3 时）
        # 顺序不能颠倒：若先 H1→H4，H4（####）会被后面的 #{2,6} 再次匹配成 H5
        if re.search(r"^#{1,3} ", text, re.MULTILINE):
            r = re.sub(r"^#{2,6} (.+)$", r"##### \1", r, flags=re.MULTILINE)
            r = re.sub(r"^# (.+)$", r"#### \1", r, flags=re.MULTILINE)

        # 3. 连续标题间增加段落间距
        r = re.sub(r"^(#{4,5} .+)\n{1,2}(#{4,5} )", r"\1\n<br>\n\2", r, flags=re.MULTILINE)

        # 4. 表格前后增加段落间距
        # 4a. 非表格行直接跟表格行时，先补一个空行
        r = re.sub(r"^([^|\n].*)\n(\|.+\|)", r"\1\n\n\2", r, flags=re.MULTILINE)
        # 4b. 表格前：在空行之前插入 <br>
        r = re.sub(r"\n\n((?:\|.+\|[^\S\n]*\n?)+)", r"\n\n<br>\n\n\1", r)
        # 4c. 表格后：在表格块末尾追加 <br>（跳过后接分隔线/标题/加粗/文末的情况）
        def _table_after(m: re.Match) -> str:
            after = r[m.end():].lstrip("\n")
            if not after or re.match(r"^(---|#{4,5} |\*\*)", after):
                return m.group(0)
            return m.group(0) + "\n<br>\n"
        r = re.sub(r"(?:^\|.+\|[^\S\n]*\n?)+", _table_after, r, flags=re.MULTILINE)
        # 4d. 表格前是普通文本（非标题、非加粗行）时，只需 <br>，去掉多余空行
        r = re.sub(r"^((?!#{4,5} )(?!\*\*).+)\n\n(<br>)\n\n(\|)", r"\1\n\2\n\3", r, flags=re.MULTILINE)
        # 4d2. 表格前是加粗行时，<br> 紧贴加粗行，空行保留在后面
        r = re.sub(r"^(\*\*.+)\n\n(<br>)\n\n(\|)", r"\1\n\2\n\n\3", r, flags=re.MULTILINE)
        # 4e. 表格后是普通文本（非标题、非加粗行）时，只需 <br>，去掉多余空行
        r = re.sub(r"(\|[^\n]*\n)\n(<br>\n)((?!#{4,5} )(?!\*\*))", r"\1\2\3", r)

        # 5. 还原代码块，并在前后追加 <br>
        for i, block in enumerate(code_blocks):
            r = r.replace(f"{mark}{i}___", f"\n<br>\n{block}\n<br>\n")

        # 6. 压缩多余空行（3 个以上连续换行 → 2 个）
        r = re.sub(r"\n{3,}", "\n\n", r)

        # 7. 剥离无效图片 key
        r = _strip_invalid_image_keys(r)

        return r
    except Exception:
        _logger.debug("optimize_markdown_style failed", exc_info=True)
        return text


def _split_long_text(text: str, limit: int = _MAX_CHUNK_CHARS) -> list[str]:
    """将超长文本按段落/换行拆分为多个不超过 limit 字符的块."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks
