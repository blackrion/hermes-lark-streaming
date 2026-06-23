"""Markdown 表格解析与飞书 Table 组件构建.

吸收自 Gawg-AI/hermes-feishu，适配本项目的 CardKit v2.0 schema 2.0 架构.

核心功能：
1. 解析 Markdown 表格语法为结构化数据（ParsedTable）
2. 自动推断列类型（number / text）
3. 构建飞书 Card 2.0 ``tag: "table"`` 元素
4. 混合内容交错：保持文本与表格的原始顺序
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger("hermes_lark_streaming")

# ── 正则：检测 Markdown 表格块 ──
_TABLE_BLOCK_RE = re.compile(
    r"((?:^\|[^\n]+\|[ \t]*\n"
    r"^\|([ \t]*:?-+:?[ \t]*\|)+[ \t]*\n?"
    r"(?:^\|[^\n]+\|[ \t]*\n?)*)+)",
    re.MULTILINE,
)

# 空行分隔，避免合并独立表格
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")

# 分隔行：| --- | :---: | ---: |
_SEPARATOR_RE = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$", re.MULTILINE)

# 飞书 Card 2.0 单卡表格硬限
_MAX_TABLES_PER_CARD = 5


@dataclass
class TableCell:
    """表格单元格."""

    text: str
    raw: str = ""

    def __post_init__(self) -> None:
        if not self.raw:
            self.raw = self.text


@dataclass
class TableColumn:
    """表格列定义."""

    name: str
    index: int
    data_type: str = "text"  # "text" | "number"
    width: str = "auto"


@dataclass
class ParsedTable:
    """解析后的表格."""

    headers: list[TableColumn] = field(default_factory=list)
    rows: list[list[TableCell]] = field(default_factory=list)
    raw_markdown: str = ""


def _parse_row(line: str) -> list[str]:
    """解析单行表格为单元格字符串列表."""
    line = line.strip()
    if not line.startswith("|") or not line.endswith("|"):
        return []
    inner = line[1:-1]
    return [cell.strip() for cell in inner.split("|")]


def _infer_column_type(values: list[str]) -> str:
    """推断列类型：所有非空值都能转为数字则为 ``number``，否则 ``text``.

    吸收自 Gawg-AI：去除常见格式化字符（逗号、百分号）后尝试 float 解析.
    """
    non_empty = [v for v in values if v.strip()]
    if not non_empty:
        return "text"
    for v in non_empty:
        cleaned = v.replace(",", "").replace("%", "").replace("¥", "").replace("$", "").strip()
        try:
            float(cleaned)
        except ValueError:
            return "text"
    return "number"


def parse_table(markdown: str) -> list[ParsedTable]:
    """解析 Markdown 中所有表格块.

    先按空行拆分以避免合并独立表格，再在每个区段内匹配表格语法.
    """
    tables: list[ParsedTable] = []
    sections = _BLANK_LINE_RE.split(markdown)
    for section in sections:
        if not section.strip():
            continue
        for match in _TABLE_BLOCK_RE.finditer(section):
            block = match.group(1)
            lines = [ln for ln in block.split("\n") if ln.strip()]
            if len(lines) < 2:
                continue

            header_cells = _parse_row(lines[0])
            if not header_cells:
                continue
            if not _SEPARATOR_RE.match(lines[1].strip()):
                continue

            columns: list[TableColumn] = [
                TableColumn(name=name, index=idx) for idx, name in enumerate(header_cells)
            ]

            data_rows: list[list[TableCell]] = []
            all_column_values: dict[int, list[str]] = {col.index: [] for col in columns}

            for line in lines[2:]:
                if _SEPARATOR_RE.match(line.strip()):
                    continue
                cells = _parse_row(line)
                if not cells:
                    continue
                row_cells: list[TableCell] = []
                for idx, cell_text in enumerate(cells):
                    if idx < len(columns):
                        row_cells.append(TableCell(text=cell_text))
                        all_column_values[idx].append(cell_text)
                    else:
                        row_cells.append(TableCell(text=cell_text))
                data_rows.append(row_cells)

            for col in columns:
                col.data_type = _infer_column_type(all_column_values.get(col.index, []))

            tables.append(ParsedTable(
                headers=columns,
                rows=data_rows,
                raw_markdown=block.strip(),
            ))
    return tables


def contains_table(markdown: str) -> bool:
    """检测文本是否包含 Markdown 表格语法."""
    for section in _BLANK_LINE_RE.split(markdown):
        if _TABLE_BLOCK_RE.search(section):
            return True
    return False


def _build_table_columns(columns: list[TableColumn]) -> list[dict[str, Any]]:
    """构建飞书 Table 列定义（Card 2.0 schema）."""
    return [
        {
            "name": f"col_{col.index}",
            "display_name": col.name,
            "width": col.width,
            "data_type": col.data_type,
        }
        for col in columns
    ]


def _build_table_rows(
    rows: list[list[TableCell]],
    columns: list[TableColumn],
) -> list[dict[str, Any]]:
    """构建飞书 Table 行数据."""
    result: list[dict[str, Any]] = []
    for row in rows:
        feishu_row: dict[str, Any] = {}
        for idx, cell in enumerate(row):
            feishu_row[f"col_{idx}"] = cell.text
        result.append(feishu_row)
    return result


def build_table_element(table: ParsedTable) -> dict[str, Any]:
    """构建飞书 Card 2.0 ``tag: "table"`` 元素."""
    return {
        "tag": "table",
        "columns": _build_table_columns(table.headers),
        "rows": _build_table_rows(table.rows, table.headers),
    }


def render_markdown_with_tables(
    markdown: str,
    *,
    max_tables: int = _MAX_TABLES_PER_CARD,
) -> list[dict[str, Any]]:
    """将 Markdown 渲染为飞书 Card 元素列表，表格使用原生 Table 组件.

    保持文本与表格的原始顺序（混合内容交错）.
    超出 ``max_tables`` 的表格降级为代码块.

    返回 ``body.elements`` 格式的元素列表，每个元素是
    ``{"tag": "markdown", ...}`` 或 ``{"tag": "table", ...}``.
    """
    if not markdown or not markdown.strip():
        return []

    tables = parse_table(markdown)

    # 无表格：整体作为 markdown 返回
    if not tables:
        return [{"tag": "markdown", "content": markdown.strip()}]

    elements: list[dict[str, Any]] = []
    tables_used = 0
    last_end = 0

    for match in _TABLE_BLOCK_RE.finditer(markdown):
        # 表格前的文本
        before = markdown[last_end:match.start()].strip()
        if before:
            elements.append({"tag": "markdown", "content": before})

        if tables_used < max_tables and tables_used < len(tables):
            # 渲染为原生 Table 组件
            elements.append(build_table_element(tables[tables_used]))
            tables_used += 1
        else:
            # 超限表格降级为代码块
            elements.append({
                "tag": "markdown",
                "content": f"```\n{match.group(0).strip()}\n```",
            })

        last_end = match.end()

    # 最后一个表格之后的文本
    remaining = markdown[last_end:].strip()
    if remaining:
        elements.append({"tag": "markdown", "content": remaining})

    return elements


__all__ = [
    "TableCell",
    "TableColumn",
    "ParsedTable",
    "parse_table",
    "contains_table",
    "build_table_element",
    "render_markdown_with_tables",
    "_infer_column_type",
]
