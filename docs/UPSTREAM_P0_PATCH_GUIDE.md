# 上游 P0 修复移植说明 — hermes-lark-streaming fork

> 基于 upstream commits e98f8d7, 2b379e4, 92825c7
> 目标分支: sync/upstream-p0-p1
> 生成时间: 2026-06-30

我们的 fork 在 0ae8d70 处分叉，之后做了 approval card / header 增强 / openclaw-lark 特性移植。
上游的修复不能直接 cherry-pick（代码偏移大），需要手动应用。

---

## 修复 1: P0-01 乘号转义 escape_markdown_asterisks

**来源**: e98f8d7 (首次) + 2b379e4 (性能优化)

### 文件 1a: cardkit/md.py

**修复逻辑**: 新增 `escape_markdown_asterisks()` 函数，保护合法 Markdown 强调结构（粗体、斜体、代码块），转义剩余的 `*`（如 `2*4000+4*3000` 中的乘号），防止飞书 Markdown 解析器将乘号误配对为斜体。

**我们代码当前状态**: cardkit/md.py **完全没有** `escape_markdown_asterisks` 函数（第 14-21 行 `__all__` 中没有它，第 63 行 `_strip_invalid_image_keys` 之后直接是 `optimize_markdown_style`）。

**需要做的修改**:

1. **第 14-21 行** — 在 `__all__` 列表中添加 `"escape_markdown_asterisks"`:

```python
# 当前 (行 14-21):
__all__ = [
    "_MAX_CRON_TABLES",
    "_downgrade_tables",
    "_find_tables_outside_code_blocks",
    "_split_long_text",
    "_strip_invalid_image_keys",
    "optimize_markdown_style",
]

# 改为:
__all__ = [
    "_MAX_CRON_TABLES",
    "_downgrade_tables",
    "_find_tables_outside_code_blocks",
    "_split_long_text",
    "_strip_invalid_image_keys",
    "escape_markdown_asterisks",
    "optimize_markdown_style",
]
```

2. **第 64 行之后**（`_strip_invalid_image_keys` 函数和 `optimize_markdown_style` 之间）— 插入完整函数:

```python
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
```

> **注意**: 使用了 2b379e4 的性能优化版本（`re.sub` 一次性还原，而非逐个 `str.replace`）。上游 e98f8d7 原始版本用 `for` 循环逐个还原，2b379e4 改成了单次 `re.sub`。我们直接用优化版本。

**冲突风险**: 低。这是纯新增代码，插入在两个现有函数之间。

---

### 文件 1b: controller/linear_mixin.py — 接入 escape_markdown_asterisks 到 7 处答案输出路径

**修复逻辑**: 在所有输出 answer_text 到卡片的路径上，用 `escape_markdown_asterisks()` 包裹内容。

**我们代码当前状态**: 导入行（第 55 行）只导入 `_downgrade_tables, optimize_markdown_style`，没有 `escape_markdown_asterisks`。

#### 修改 1: 导入 (第 55 行)

```python
# 当前:
from ..cardkit.md import _downgrade_tables, optimize_markdown_style

# 改为:
from ..cardkit.md import _downgrade_tables, escape_markdown_asterisks, optimize_markdown_style
```

#### 修改 2: IM 降级封卡路径 (第 452-453 行)

```python
# 当前 (行 452-453):
            elif state and state.answer_text:
                content = state.answer_text

# 改为:
            elif state and state.answer_text:
                content = escape_markdown_asterisks(state.answer_text)
```

#### 修改 3: 流式 answer 路径 1 (第 639 行)

```python
# 当前 (行 639):
                content = state.answer_text or " "

# 改为:
                content = escape_markdown_asterisks(state.answer_text or " ")
```

#### 修改 4: 流式 answer 路径 2 (第 783 行)

```python
# 当前 (行 783):
            content = state.answer_text or " "

# 改为:
            content = escape_markdown_asterisks(state.answer_text or " ")
```

#### 修改 5: seal drain answer (第 1031 行)

```python
# 当前 (行 1031):
                    content = state.answer_text or " "

# 改为:
                    content = escape_markdown_asterisks(state.answer_text or " ")
```

#### 修改 6: seal Step 2 — partial_update_element (第 1102 行)

```python
# 当前 (行 1102):
                optimized_content = _downgrade_tables(optimize_markdown_style(state.answer_text)) or " "

# 改为:
                optimized_content = escape_markdown_asterisks(_downgrade_tables(optimize_markdown_style(state.answer_text))) or " "
```

#### 修改 7: retry 路径 partial_update_element (第 1400 行)

```python
# 当前 (行 1400):
                                optimized_content = _downgrade_tables(optimize_markdown_style(state.answer_text)) or " "

# 改为:
                                optimized_content = escape_markdown_asterisks(_downgrade_tables(optimize_markdown_style(state.answer_text))) or " "
```

#### 修改 8: drain answer 路径 (第 1585 行)

```python
# 当前 (行 1585):
                content = state.answer_text or " "

# 改为:
                content = escape_markdown_asterisks(state.answer_text or " ")
```

**冲突风险**: 低-中。我们的 fork 有 header 增强，但 answer 输出路径的基本结构与上游一致。需要注意行 411 `content = state.answer_text or "处理中..."` **不要改**（这是 loading 状态文本，不是 answer 输出）。区分方法是看是否在 `answer_dirty` 或 `answer_text` 条件块内。

---

## 修复 2: P0-02 工具耗时 started_at=None

**来源**: e98f8d7

### 文件: state/tooluse.py

**修复逻辑**: `ToolStep.started_at` 和 `ToolSession.started_at` 的默认值从 `0.0` 改为 `None`。`elapsed_ms` 属性和计算处加 `is None` 守卫，防止未启动时计算出 17 亿毫秒（`time.time() - 0.0` 的结果）。

**我们代码当前状态**: 与上游修复前完全一致（分叉时即有此 bug）。

#### 修改 1: ToolStep.started_at (第 42 行)

```python
# 当前 (行 42):
    started_at: float = 0.0

# 改为:
    started_at: float | None = None
```

#### 修改 2: ToolSession.started_at (第 49 行)

```python
# 当前 (行 49):
    started_at: float = 0.0

# 改为:
    started_at: float | None = None
```

#### 修改 3: elapsed_ms 属性守卫 (第 377-379 行)

```python
# 当前 (行 376-379):
    @property
    def elapsed_ms(self) -> float:
        if self._session is None:
            return 0.0
        return (time.time() - self._session.started_at) * 1000

# 改为:
    @property
    def elapsed_ms(self) -> float:
        if self._session is None or self._session.started_at is None:
            return 0.0
        return (time.time() - self._session.started_at) * 1000
```

#### 修改 4: record_end 中的 elapsed_ms 计算 (第 406 行)

```python
# 当前 (行 406):
                step.elapsed_ms = (time.time() - step.started_at) * 1000

# 改为:
                step.elapsed_ms = (time.time() - step.started_at) * 1000 if step.started_at is not None else 0.0
```

**冲突风险**: 无。tooluse.py 在分叉后没有被我们的 fork 修改过。

---

## 修复 3: P0-03 Clarify 选项乱码 _normalize_choice + 并发锁

**来源**: 2b379e4

这个修复分两部分：(A) Clarify 选项归一化，(B) 并发安全锁。

### 文件 3A: cardkit/special.py — Clarify 选项归一化

**修复逻辑**: LLM 有时输出 dict 形式的选项（如 `{"id": 1, "path": "/mnt/nas/backup1"}`），被 `str()` 序列化后变成 `"{'id': 1, 'path': '/mnt/nas/backup1'}"`。飞书 lark_md 会把 `{'` 解析为模板语法导致乱码。新增 `_normalize_choice()` 用 `ast.literal_eval` 解析 dict-repr 字符串，按字段优先级提取可读文本；新增 `normalize_clarify_choices()` 处理列表。同时在 `build_clarify_card` 中对 question 和 choices 做 `_escape_md` 转义。

**我们代码当前状态**: cardkit/special.py 没有 `_normalize_choice`、`normalize_clarify_choices` 函数。导入只有 `_build_header`，没有 `_escape_md`。

#### 修改 1: 导入 (第 7-17 行)

```python
# 当前 (行 7-17):
from typing import Any

from .i18n import _LOCALES, _T, _i18n, _t
from .md import (
    _MAX_CRON_TABLES,
    _downgrade_tables,
    _split_long_text,
    optimize_markdown_style,
)
from .table import render_markdown_with_tables
from .elements import _build_header

# 改为:
import ast
from typing import Any

from .i18n import _LOCALES, _T, _i18n, _t
from .md import (
    _MAX_CRON_TABLES,
    _downgrade_tables,
    _split_long_text,
    optimize_markdown_style,
)
from .table import render_markdown_with_tables
from .elements import _build_header, _escape_md
```

#### 修改 2: __all__ (第 21-29 行)

```python
# 当前 (行 21-29):
__all__ = [
    'build_cron_card',
    'build_gateway_card',
    'build_clarify_card',
    'build_clarify_submitted_card',
    'build_clarify_confirmed_card',
    'build_approval_card',
    'build_approval_resolved_card',
]

# 改为:
__all__ = [
    'build_cron_card',
    'build_gateway_card',
    'build_clarify_card',
    'build_clarify_submitted_card',
    'build_clarify_confirmed_card',
    'build_approval_card',
    'build_approval_resolved_card',
    'normalize_clarify_choices',
]
```

#### 修改 3: 在 `__all__` 之后、`_summary` 函数之前（第 29 行之后）插入归一化函数

```python

# ── Clarify choice normalization (v1.3.0 P0-01) ──────────────────────

_CLARIFY_DICT_FIELD_PRIORITY = (
    "label", "description", "text", "title",
    "name", "path", "value", "id",
)

_CLARIFY_MAX_CHOICE_LEN = 80


def _normalize_choice(choice: Any) -> str:
    """Normalize a single clarify choice into a readable display string."""
    if choice is None:
        return ""
    if not isinstance(choice, str):
        if isinstance(choice, dict):
            return _extract_readable_from_dict(choice)
        if isinstance(choice, (list, tuple)):
            parts = [_normalize_choice(x) for x in choice]
            return " ".join(p for p in parts if p)[:_CLARIFY_MAX_CHOICE_LEN]
        choice = str(choice)

    text = choice.strip()
    if not text:
        return ""

    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            extracted = _extract_readable_from_dict(parsed)
            if extracted:
                text = extracted

    if len(text) > _CLARIFY_MAX_CHOICE_LEN:
        text = text[: _CLARIFY_MAX_CHOICE_LEN - 1] + "…"

    return text


def _extract_readable_from_dict(d: dict) -> str:
    """Extract the most human-readable string field from a dict."""
    for field in _CLARIFY_DICT_FIELD_PRIORITY:
        val = d.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def normalize_clarify_choices(choices: list[str] | None) -> list[str]:
    """Normalize a list of clarify choices for both display and AI resolution."""
    if not choices:
        return []
    normalized = []
    for c in choices:
        n = _normalize_choice(c)
        if n:
            normalized.append(n)
    return normalized
```

#### 修改 4: build_clarify_card — question 转义 + choices 归一化 (第 188-189 行)

```python
# 当前 (行 188-189):
        "text": {
            "tag": "lark_md",
            "content": f"**{question}**",
        },

# 改为:
        "text": {
            "tag": "lark_md",
            "content": f"**{_escape_md(question)}**",
        },
```

#### 修改 5: build_clarify_card — choices 归一化 + 转义 (第 193-198 行)

```python
# 当前 (行 193-198):
    if choices:
        # ── Markdown 全量展示选项列表 ──
        option_lines = []
        for i, choice in enumerate(choices):
            label = chr(ord("A") + i)  # A, B, C, ...
            option_lines.append(f"{label}. {choice}")

# 改为:
    # v1.3.0 P0-01: normalize choices (dict-repr → readable)
    normalized_choices = normalize_clarify_choices(choices)

    if normalized_choices:
        # ── Markdown 全量展示选项列表（转义 lark_md 特殊字符） ──
        option_lines = []
        for i, choice in enumerate(normalized_choices):
            label = chr(ord("A") + i)  # A, B, C, ...
            option_lines.append(f"{label}. {_escape_md(choice)}")
```

#### 修改 6: build_clarify_card — select_static options 用归一化文本 (第 206-212 行)

```python
# 当前 (行 206-212):
        options: list[dict[str, Any]] = []
        for i, choice in enumerate(choices):
            label = chr(ord("A") + i)
            options.append({
                "text": {"tag": "plain_text", "content": f"{label}. {choice}"},
                "value": str(i),
            })

# 改为:
        # plain_text 不做 markdown 渲染，无需转义；但需用 normalized 文本
        options: list[dict[str, Any]] = []
        for i, choice in enumerate(normalized_choices):
            label = chr(ord("A") + i)
            options.append({
                "text": {"tag": "plain_text", "content": f"{label}. {choice}"},
                "value": str(i),
            })
```

#### 修改 7: build_clarify_submitted_card — selected 转义 + question 转义 (第 522-524 行, 540 行)

```python
# 当前 (行 522-524):
    en_selected, zh_selected = _T["clarify_selected"]
    en_sel_label = en_selected.format(selected)
    zh_sel_label = zh_selected.format(selected)

# 改为:
    # v1.3.0 P0-01: escape the selected text for lark_md
    safe_selected = _escape_md(selected)
    en_selected, zh_selected = _T["clarify_selected"]
    en_sel_label = en_selected.format(safe_selected)
    zh_sel_label = zh_selected.format(safe_selected)
```

```python
# 当前 (行 540):
                "content": f"**{question}**",

# 改为:
                "content": f"**{_escape_md(question)}**",
```

#### 修改 8: build_clarify_confirmed_card — selected 转义 + question 转义 (第 620-622 行, 637 行)

```python
# 当前 (行 620-622):
    en_selected, zh_selected = _T["clarify_selected"]
    en_sel_label = en_selected.format(selected)
    zh_sel_label = zh_selected.format(selected)

# 改为:
    # v1.3.0 P0-01: escape the selected text for lark_md
    safe_selected = _escape_md(selected)
    en_selected, zh_selected = _T["clarify_selected"]
    en_sel_label = en_selected.format(safe_selected)
    zh_sel_label = zh_selected.format(safe_selected)
```

```python
# 当前 (行 637):
                "content": f"**{question}**",

# 改为:
                "content": f"**{_escape_md(question)}**",
```

**冲突风险**: 中。我们的 fork 对 special.py 有改动（approval card 等），但 clarify 相关函数结构一致。需要注意我们的 `build_clarify_card` 的 label 生成逻辑与上游略有不同：我们用 `chr(ord("A") + i)`（不支持 26 个以上选项），上游用 `chr(ord("A") + i) if i < 26 else str(i + 1)`。这不影响修复移植。

---

### 文件 3B: patching/adapter.py — Clarify 并发锁 + 归一化接入

**修复逻辑**: 5 个 `_clarify_*` 字典从多线程访问（event-loop 线程 + webhook 回调线程 + 定时协程），新增 `_clarify_lock` 保护所有访问点。在 `_wrap_feishu_adapter_send_clarify` 中调用 `normalize_clarify_choices` 归一化后再存储。`_schedule_confirm_card` 和 `_handle_clarify_card_action` 中的字典访问也加锁。

#### 修改 1: 添加 threading 导入 (第 13-17 行)

```python
# 当前 (行 13-17):
import asyncio
import logging
from typing import Any, Callable

# 改为:
import asyncio
import logging
import threading
from typing import Any, Callable
```

#### 修改 2: 添加 _clarify_lock (第 489-493 行)

```python
# 当前 (行 489-493):
_clarify_choices: dict[str, list[str]] = {}  # clarify_id → choices list
_clarify_questions: dict[str, str] = {}  # clarify_id → question text
_clarify_card_msg_ids: dict[str, str] = {}  # clarify_id → card_msg_id (for server-side confirm update)
_clarify_selections: dict[str, str] = {}  # clarify_id → user's selected/input text (for retry)

# 改为:
# v1.3.0: protect all 5 clarify dicts with a single coarse-grained lock
_clarify_lock = threading.Lock()
_clarify_choices: dict[str, list[str]] = {}  # clarify_id → choices list (normalized)
_clarify_questions: dict[str, str] = {}  # clarify_id → question text
_clarify_card_msg_ids: dict[str, str] = {}  # clarify_id → card_msg_id (for server-side confirm update)
_clarify_selections: dict[str, str] = {}  # clarify_id → user's selected/input text (for retry)
```

> **注意**: 我们 fork 的 adapter.py 没有 `_clarify_timestamps` 字典（上游有，用于 TTL 过期清理）。所以我们不需要上游 2b379e4 中 `_prune_expired_clarify` 相关的改动。如果将来需要 TTL 清理功能，需要单独移植。

#### 修改 3: _wrap_feishu_adapter_send_clarify — 归一化 choices (第 534-545 行)

```python
# 当前 (行 534-545):
            from ..cardkit import build_clarify_card

            card = build_clarify_card(
                question=question,
                choices=choices if choices else None,
                clarify_id=clarify_id,
            )

            # Store choices and question for callback lookup
            if choices:
                _clarify_choices[clarify_id] = list(choices)
            _clarify_questions[clarify_id] = question

# 改为:
            from ..cardkit import build_clarify_card, normalize_clarify_choices

            # v1.3.0 P0-01: normalize choices BEFORE building card and storing
            normalized = normalize_clarify_choices(choices) if choices else None

            card = build_clarify_card(
                question=question,
                choices=normalized,
                clarify_id=clarify_id,
            )

            # Store normalized choices and question for callback lookup
            with _clarify_lock:
                if normalized:
                    _clarify_choices[clarify_id] = list(normalized)
                _clarify_questions[clarify_id] = question
```

#### 修改 4: card_msg_id 存储 (第 569-571 行)

```python
# 当前 (行 569-571):
            # Store card_msg_id for server-side confirm update
            if card_msg_id:
                _clarify_card_msg_ids[clarify_id] = card_msg_id

# 改为:
            # Store card_msg_id for server-side confirm update
            with _clarify_lock:
                if card_msg_id:
                    _clarify_card_msg_ids[clarify_id] = card_msg_id
```

#### 修改 5: _schedule_confirm_card — 快照 + cleanup 函数 (第 659-674 行)

```python
# 当前 (行 659-674):
    card_msg_id = _clarify_card_msg_ids.get(cid, "")
    question = _clarify_questions.get(cid, "")
    choices = _clarify_choices.get(cid) or None
    selected = _clarify_selections.get(cid, "")

    if not card_msg_id:
        _logger.warning(
            "clarify card: cannot confirm, no card_msg_id for clarify_id=%s",
            (cid or "?")[:12],
        )
        # Still cleanup
        _clarify_choices.pop(cid, None)
        _clarify_questions.pop(cid, None)
        _clarify_card_msg_ids.pop(cid, None)
        _clarify_selections.pop(cid, None)
        return

    if not selected:
        _logger.warning(
            "clarify card: cannot confirm, no stored selection for clarify_id=%s",
            (cid or "?")[:12],
        )
        _clarify_choices.pop(cid, None)
        _clarify_questions.pop(cid, None)
        _clarify_card_msg_ids.pop(cid, None)
        _clarify_selections.pop(cid, None)
        return

# 改为:
    # v1.3.0: snapshot all needed data under the lock, then release
    with _clarify_lock:
        card_msg_id = _clarify_card_msg_ids.get(cid, "")
        question = _clarify_questions.get(cid, "")
        selected = _clarify_selections.get(cid, "")

    def _cleanup():
        """Pop all stored entries for this clarify_id (idempotent)."""
        with _clarify_lock:
            _clarify_choices.pop(cid, None)
            _clarify_questions.pop(cid, None)
            _clarify_card_msg_ids.pop(cid, None)
            _clarify_selections.pop(cid, None)

    if not card_msg_id:
        _logger.warning(
            "clarify card: cannot confirm, no card_msg_id for clarify_id=%s",
            (cid or "?")[:12],
        )
        _cleanup()
        return

    if not selected:
        _logger.warning(
            "clarify card: cannot confirm, no stored selection for clarify_id=%s",
            (cid or "?")[:12],
        )
        _cleanup()
        return
```

#### 修改 6: _schedule_confirm_card — finally 块 cleanup (第 715-721 行)

```python
# 当前 (行 715-721):
    finally:
        # Always cleanup stored data after confirm attempt
        _clarify_choices.pop(cid, None)
        _clarify_questions.pop(cid, None)
        _clarify_card_msg_ids.pop(cid, None)
        _clarify_selections.pop(cid, None)

# 改为:
    finally:
        # Always cleanup stored data after confirm attempt
        _cleanup()
```

#### 修改 7: _handle_clarify_card_action — question + choices 快照 (第 795-796 行)

```python
# 当前 (行 795-796):
    question = _clarify_questions.get(clarify_id, "")
    choices = _clarify_choices.get(clarify_id) or None

# 改为:
    # v1.3.0: snapshot question + choices atomically
    with _clarify_lock:
        question = _clarify_questions.get(clarify_id, "")
        choices = _clarify_choices.get(clarify_id) or None
```

#### 修改 8: _handle_clarify_card_action — retry_submit 读取 selection (第 800 行)

```python
# 当前 (行 800):
        stored_selection = _clarify_selections.get(clarify_id, "")

# 改为:
        with _clarify_lock:
            stored_selection = _clarify_selections.get(clarify_id, "")
```

#### 修改 9: _handle_clarify_card_action — select 读取 choices_list (第 852 行)

```python
# 当前 (行 852):
        choices_list = _clarify_choices.get(clarify_id, [])

# 改为:
        with _clarify_lock:
            choices_list = list(_clarify_choices.get(clarify_id, []))
```

#### 修改 10: _handle_clarify_card_action — select 存储 selection (第 872 行)

```python
# 当前 (行 872):
        _clarify_selections[clarify_id] = choice_text

# 改为:
        with _clarify_lock:
            _clarify_selections[clarify_id] = choice_text
```

#### 修改 11: _handle_clarify_card_action — input_submit 存储 (第 927 行)

```python
# 当前 (行 927):
        _clarify_selections[clarify_id] = input_text

# 改为:
        with _clarify_lock:
            _clarify_selections[clarify_id] = input_text
```

#### 修改 12: _handle_clarify_card_action — button_submit 存储 (第 983 行)

```python
# 当前 (行 983):
        _clarify_selections[clarify_id] = input_text

# 改为:
        with _clarify_lock:
            _clarify_selections[clarify_id] = input_text
```

> **注意**: 上面 input_submit 和 button_submit 的代码完全相同（`_clarify_selections[clarify_id] = input_text`），所以需要用 `replace_all=true` 或者带上下文区分。建议用上下文区分（分别带前后的 `# Store selection for retry` 注释或前面的 if 块）。

**冲突风险**: 中-高。adapter.py 是我们 fork 改动最多的文件之一（approval card 等），但 clarify 相关代码块结构一致。需要逐个修改点验证。

---

## 修复 4: P0-04 封卡末尾内容裁剪

**来源**: 92825c7

**修复逻辑**: 上游 v1.3.0 引入了 `_answer_finalized_via_stream` 标志，当 answer 通过 `stream_element` 推送后，seal 时跳过最终的 `partial_update_element`（避免 bypass 飞书打字机队列导致"瞬间输出"）。但这导致飞书异步打字机队列中未渲染的字符在 `close_streaming` 时被永久丢弃。v1.3.1 修复：移除该守卫，seal **永远**发送最终 `partial_update_element`。

**我们代码当前状态**: **不需要此修复**。我们的 fork 从未引入 `_answer_finalized_via_stream` 标志（我们在 0ae8d70 分叉，早于 v1.3.0）。我们的 seal 路径（第 1101 行）已经是无条件发送：

```python
# 我们的代码 (行 1101):
if state is not None and state.answer_text and "answer" in session._creation_stages:
```

这正是上游 v1.3.1 修复后的目标状态。无需任何修改。

同样，retry 路径（第 1399 行）也是无条件发送：

```python
# 我们的代码 (行 1399):
if state.answer_text and "answer" in session._creation_stages:
```

### 附带修复 F-03: 删除无效的 cardkit_extend_ttl 功能

**来源**: 92825c7

**修复逻辑**: 真飞书 API 实测 `streaming_config.ttl_seconds` 返回 300122 'unknown property'，该功能完全无效。删除 `cardkit_extend_ttl` 方法 + TTL 延长调用点 + 常量。

**我们代码当前状态**: 仍然有 TTL 延长代码。

#### 修改 1: 删除 TTL 常量 (controller/linear_mixin.py 第 90-94 行)

```python
# 当前 (行 90-94), 删除整段:
# ---------------------------------------------------------------------------
# TTL proactive extension
# ---------------------------------------------------------------------------

_TTL_EXTEND_THRESHOLD_SEC = 540.0  # Extend TTL when card has lived > 540s
_TTL_EXTEND_DELTA_SEC = 600        # Extend by 600s
```

#### 修改 2: 删除 TTL 延长调用 (controller/linear_mixin.py 第 507-522 行)

```python
# 当前 (行 507-522), 删除整段:
        # ── TTL proactive extension ──
        if session.card_created_at and _time.time() - session.card_created_at > _TTL_EXTEND_THRESHOLD_SEC:
            try:
                session.sequence += 1
                await self._client.cardkit_extend_ttl(
                    session.card_id,
                    ttl_seconds=_TTL_EXTEND_DELTA_SEC,
                    sequence=session.sequence,
                )
                _logger.info(
                    "TTL extended: card=%s seq=%d",
                    session.card_id[:12],
                    session.sequence,
                )
            except Exception:
                _logger.debug("TTL extend failed, ignoring", exc_info=True)

```

> 删除后，`assert self._client is not None` (第 505 行) 后直接跟 `actions: list[dict[str, Any]] = []` (第 524 行)。

#### 修改 3: 删除 cardkit_extend_ttl 方法 (feishu/client.py)

需要在 feishu/client.py 中找到 `cardkit_extend_ttl` 方法并整段删除。

**冲突风险**: 低。TTL 代码在我们的 fork 中未被改动过，删除是纯删除操作。但需要同步清理 tests/ 中引用 `cardkit_extend_ttl` 的 mock（tests/test_controller.py, tests/e2e/framework.py, tests/e2e/mock_feishu.py）。

---

### 附带修复 F-01/F-02: flush_interval_ms 默认值 100→200

**来源**: 92825c7

**修复逻辑**: v1.2.1 将默认值从 100 改为 200，v1.3.0 回退到 100，v1.3.1 又恢复到 200。生产日志显示 100ms 与 200ms 打字机效果无差别，但 200ms 可将 API 调用量减半。

**我们代码当前状态**: 默认值 100（config/reader.py 第 148 行）。

#### 修改: config/reader.py 第 148 行

```python
# 当前 (行 148):
        ms = float(sec.get("flush_interval_ms", 100))

# 改为:
        ms = float(sec.get("flush_interval_ms", 200))
```

同时更新 docstring（第 142-146 行）中的 "默认 100ms" 说明改为 "默认 200ms"。

**冲突风险**: 低。但需注意 flush_interval_sec 的 docstring（第 153-155 行）也提到 "默认 0.1 秒（100ms）"，应一并更新为 "默认 0.2 秒（200ms）"。

---

## 修复 5 (附赠): 并发安全 — controller/core.py + controller/linear_mixin.py

**来源**: 2b379e4

**修复逻辑**: `_sessions` 字典在 event-loop 线程和 worker 线程之间共享，存在竞态条件。新增 `_sessions_lock` (RLock) + 7 个线程安全 helper (`_sess_get`, `_sess_put`, `_sess_pop`, `_sess_items_snapshot`, `_sess_values_snapshot`, `_sess_active_count`, `_sess_clear`)。`_interrupt_map` 新增独立锁。

**我们代码当前状态**: 完全没有并发保护（controller/core.py 第 48-49 行直接用裸 dict）。

> **评估**: 这是 P1 级别的修复，不是 P0。如果当前没有遇到并发崩溃，可以后续单独移植。但如果要完整移植 2b379e4 的所有改动，需要：
> 1. controller/core.py: 添加 `_sessions_lock`, `_interrupt_map_lock`, 7 个 helper 方法，替换所有 `self._sessions.xxx()` 调用为 `self._sess_xxx()` 调用
> 2. patching/adapter.py: 替换 `_ctrl._sessions.get(eid)` → `_ctrl._sess_get(eid)`，`list(_ctrl._sessions.values())` → `_ctrl._sess_values_snapshot()`
>
> 涉及 controller/core.py 中约 23 处 `_sessions` / `_interrupt_map` 访问点的修改。
> **冲突风险**: 高（与我们 fork 的 header 增强代码在同一文件中）。

---

## 移植优先级建议

| 优先级 | 修复 | 文件数 | 冲突风险 | 影响 |
|--------|------|--------|----------|------|
| P0 | 乘号转义 | md.py + linear_mixin.py | 低-中 | 防止乘号消失/数字拼合 |
| P0 | 工具耗时 None | tooluse.py | 无 | 防止 17 亿毫秒显示 |
| P0 | Clarify 乱码 | special.py + adapter.py | 中-高 | 防止选项显示乱码 |
| P0 | 封卡裁剪 | (无需修改) | 无 | 我们已经是正确状态 |
| P1 | TTL 删除 | linear_mixin.py + client.py | 低 | 清理无效功能 |
| P1 | flush 200ms | reader.py | 低 | API 调用量减半 |
| P1 | 并发安全 | core.py + adapter.py | 高 | 防止 RuntimeError 崩溃 |

建议按优先级从上到下逐个移植，每移植一个修复后运行测试验证。
