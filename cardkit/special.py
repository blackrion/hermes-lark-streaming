"""CardKit v2.0 — Specialized card types: cron, gateway, clarify."""



from __future__ import annotations

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



__all__ = [
    'build_cron_card',
    'build_gateway_card',
    'build_clarify_card',
    'build_clarify_submitted_card',
    'build_clarify_confirmed_card',
    'build_approval_card',
    'build_approval_resolved_card',
]


def _summary(text: str) -> dict[str, Any]:
    """Build Feishu list-summary text with i18n fallback."""
    summary = text[:120].replace("\n", " ").replace("```", "").strip()
    return {"content": summary, "i18n_content": _i18n(summary, summary)}


_GATEWAY_CATEGORY_HEADER: dict[str, tuple[str, tuple[str, str]]] = {
    "auth": ("approval", ("Authentication", "认证消息")),
    "error": ("error", ("Gateway error", "网关错误")),
    "session": ("completed", ("Session update", "会话更新")),
    "slash": ("gateway", ("Command response", "命令响应")),
    "system": ("gateway", ("System notification", "系统通知")),
}


def _append_rendered_markdown(
    elements: list[dict[str, Any]],
    content: str,
    *,
    enable_native_tables: bool,
    max_tables: int = _MAX_CRON_TABLES,
) -> None:
    """Append markdown/table elements according to native-table config."""
    optimized = optimize_markdown_style(content)
    if enable_native_tables:
        rendered = render_markdown_with_tables(optimized, max_tables=max_tables)
    else:
        rendered = [{
            "tag": "markdown",
            "content": _downgrade_tables(optimized, limit=max_tables),
        }]

    for el in rendered:
        if el.get("tag") == "markdown":
            for chunk in _split_long_text(el.get("content", "")):
                if chunk.strip():
                    elements.append({"tag": "markdown", "content": chunk})
        else:
            elements.append(el)


def build_cron_card(
    content: str,
    *,
    enable_native_tables: bool = True,
) -> dict[str, Any]:
    """Cron 推送卡片 — colored header + markdown/native-table body."""
    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"locales": _LOCALES, "streaming_mode": False},
        "header": _build_header(
            "cron",
            subtitle=("Scheduled delivery", "定时任务推送"),
        ),
        "body": {"elements": []},
    }
    if not content.strip():
        return card
    card["config"]["summary"] = _summary(content)
    _append_rendered_markdown(
        card["body"]["elements"],
        content,
        enable_native_tables=enable_native_tables,
        max_tables=_MAX_CRON_TABLES,
    )
    return card


def build_gateway_card(
    content: str,
    *,
    category: str = "",
    status_label: str = "",
    status_emoji: str = "",
    enable_native_tables: bool = True,
) -> dict[str, Any]:
    """Gateway-internal message card — colored header + clean content body.

    Used for slash command replies, auth messages, session lifecycle
    notifications, errors, and all non-AI text that Hermes sends to Feishu.
    """
    elements: list[dict[str, Any]] = []

    # ── Status indicator (from reaction interception) ──
    if status_label and status_emoji:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": f"{status_emoji} {status_label}",
                "text_color": "turquoise",
                "text_size": "notation",
            },
        })

    if content.strip():
        _append_rendered_markdown(
            elements,
            content,
            enable_native_tables=enable_native_tables,
            max_tables=_MAX_CRON_TABLES,
        )

    header_status, subtitle = _GATEWAY_CATEGORY_HEADER.get(
        category or "system",
        _GATEWAY_CATEGORY_HEADER["system"],
    )
    if status_label:
        label = f"{status_emoji} {status_label}".strip()
        subtitle = (label, label)

    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"locales": _LOCALES, "streaming_mode": False},
        "header": _build_header(header_status, subtitle=subtitle),
        "body": {"elements": elements},
    }

    if content.strip():
        card["config"]["summary"] = _summary(content)
    return card


def build_clarify_card(
    *,
    question: str,
    choices: list[str] | None = None,
    clarify_id: str = "",
) -> dict[str, Any]:
    """构建 Clarify 待选择态卡片（State 1: Pending）.

    三态卡片设计 — 待选择态:
      - 彩色 header: 延续运行卡/上游优秀 UI 的状态化视觉
      - 标题: helpdesk_outlined 图标 + 问题文本
      - 选项列表: markdown 全量展示所有选项（A. B. C.）
      - 快速选择: select_static 下拉框（仅含预定义选项，无 "其他" 选项）
      - 自定义输入: input 文本输入框（支持 Enter + 按钮提交）
      - 无 choices 时仅显示 input 输入框

    Args:
        question: 问题文本
        choices: 选项列表，None/空表示开放式问题
        clarify_id: 唯一标识，用于回调路由
    """
    elements: list[dict[str, Any]] = []

    # ── 问题标题 (helpdesk_outlined icon) ──
    elements.append({
        "tag": "div",
        "icon": {
            "tag": "standard_icon",
            "token": "info_outlined",
            "size": "20px 20px",
            "color": "blue",
        },
        "text": {
            "tag": "lark_md",
            "content": f"**{question}**",
        },
    })

    if choices:
        # ── Markdown 全量展示选项列表 ──
        option_lines = []
        for i, choice in enumerate(choices):
            label = chr(ord("A") + i)  # A, B, C, ...
            option_lines.append(f"{label}. {choice}")
        options_md = "\n".join(option_lines)
        elements.append({
            "tag": "markdown",
            "content": options_md,
        })

        # ── 快速选择: select_static 下拉框（无 "其他" 选项） ──
        options: list[dict[str, Any]] = []
        for i, choice in enumerate(choices):
            label = chr(ord("A") + i)
            options.append({
                "text": {"tag": "plain_text", "content": f"{label}. {choice}"},
                "value": str(i),
            })

        en_placeholder, zh_placeholder = _T["clarify_select_placeholder"]
        select_el: dict[str, Any] = {
            "tag": "select_static",
            "element_id": "clarify_select",
            "placeholder": {
                "tag": "plain_text",
                "content": en_placeholder,
                "i18n_content": _i18n(en_placeholder, zh_placeholder),
            },
            "options": options,
            "behaviors": [{
                "type": "callback",
                "value": {
                    "hermes_clarify_action": "select",
                    "clarify_id": clarify_id,
                },
            }],
        }
        elements.append(select_el)

    # ── 自定义输入: input 文本输入框（始终显示） ──
    en_input_ph, zh_input_ph = _T["clarify_input_placeholder"]
    input_el: dict[str, Any] = {
        "tag": "input",
        "element_id": "clarify_input",
        "placeholder": {
            "tag": "plain_text",
            "content": en_input_ph,
            "i18n_content": _i18n(en_input_ph, zh_input_ph),
        },
        "max_length": 500,
        "name": "clarify_input",
        "behaviors": [{
            "type": "callback",
            "value": {
                "hermes_clarify_action": "input_submit",
                "clarify_id": clarify_id,
            },
        }],
    }
    elements.append(input_el)

    summary_text = question or "Clarification required"
    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {
            "streaming_mode": False,
            "locales": _LOCALES,
            "summary": _summary(summary_text),
        },
        "header": _build_header(
            "clarify",
            title=("Hermes Clarification", "Hermes 澄清确认"),
            subtitle=("Choose an option or type a custom answer", "请选择选项或输入自定义回答"),
        ),
        "body": {"elements": elements},
    }
    return card


def build_approval_card(
    *,
    tool_name: str = "",
    command: str = "",
    description: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """构建 Authorization/Approval 请求卡片 (CardKit 2.0).

    Ported from openclaw-lark ``buildConfirmCard()`` (MIT, ByteDance) and
    adapted to Hermes' four-button approval flow.

    Design:
      - Colored header: shield_color icon + tool/command name
      - Command preview: fenced code block (truncated to 3000 chars)
      - Description: markdown body with reason/context
      - Four approval buttons in a 2×2 column grid:
          ✅ Allow Once   — approve this single execution
          🔁 This Session — auto-approve within current session
          ⭐ Always       — permanently whitelist
          ❌ Deny          — reject (danger style)

    Args:
        tool_name: Tool or command name requesting authorization.
        command: Full command text for preview (truncated to 3000 chars).
        description: Authorization description/reason.
        approval_id: Unique ID for callback routing.
    """
    elements: list[dict[str, Any]] = []

    # ── Title with shield icon ──
    title_text = f"🔐 **{tool_name}**" if tool_name else "🔐 **Authorization Required**"
    elements.append({
        "tag": "div",
        "icon": {
            "tag": "standard_icon",
            "token": "shield_color",
            "size": "20px 20px",
            "color": "orange",
        },
        "text": {
            "tag": "lark_md",
            "content": title_text,
        },
    })

    # ── Command preview in code block (inspired by openclaw-lark ConfirmData.preview) ──
    if command.strip():
        cmd_preview = command[:3000]
        if len(command) > 3000:
            cmd_preview += "..."
        elements.append({
            "tag": "markdown",
            "content": "```\n" + cmd_preview + "\n```",
        })

    # ── Description / reason ──
    if description:
        elements.append({
            "tag": "markdown",
            "content": f"**Reason:** {description}",
        })

    # ── Separator before buttons ──
    elements.append({"tag": "hr"})

    # ── Four-button grid (2×2 column layout) ──
    def _button(text: str, btn_type: str, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": text},
            "type": btn_type,
            "behaviors": [{"type": "callback", "value": value}],
        }

    callback_value: dict[str, Any] = {"approval_id": approval_id}

    elements.append({
        "tag": "column_set",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    _button(
                        "✅ Allow Once",
                        "primary",
                        {**callback_value, "hermes_action": "approve_once"},
                    ),
                ],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    _button(
                        "🔁 This Session",
                        "default",
                        {**callback_value, "hermes_action": "approve_session"},
                    ),
                ],
            },
        ],
    })

    elements.append({
        "tag": "column_set",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    _button(
                        "⭐ Always",
                        "default",
                        {**callback_value, "hermes_action": "approve_always"},
                    ),
                ],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    _button(
                        "❌ Deny",
                        "danger",
                        {**callback_value, "hermes_action": "deny"},
                    ),
                ],
            },
        ],
    })

    summary_text = tool_name or command[:80] or description or "Authorization required"
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": False,
            "locales": _LOCALES,
            "summary": _summary(summary_text),
        },
        "header": _build_header(
            "approval",
            title=("Hermes Approval", "Hermes 授权请求"),
            subtitle=("Tool execution needs your confirmation", "工具执行需要你的确认"),
        ),
        "body": {"elements": elements},
    }


def build_approval_resolved_card(
    *,
    choice: str,
    user_name: str = "",
    tool_name: str = "",
) -> dict[str, Any]:
    """构建 Approval 已决态卡片 (CardKit 2.0) — resolved terminal state.

    Replaces Hermes' native Card 1.0 ``_build_resolved_approval_card``
    with a styled CardKit 2.0 card for visual consistency.

    Args:
        choice: One of "once", "session", "always", "deny".
        user_name: Name of the user who clicked the button.
        tool_name: Original tool/command name (for context).
    """
    is_deny = choice == "deny"
    icon = "❌" if is_deny else "✅"
    label_map = {
        "once": ("Approved Once", "已允许一次"),
        "session": ("Approved for Session", "本会话已允许"),
        "always": ("Approved Permanently", "已永久允许"),
        "deny": ("Denied", "已拒绝"),
    }
    en_label, zh_label = label_map.get(choice, ("Resolved", "已处理"))

    header_status = "error" if is_deny else "completed"

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "icon": {
                "tag": "standard_icon",
                "token": "close_color" if is_deny else "check_circle_color",
                "size": "20px 20px",
                "color": "red" if is_deny else "green",
            },
            "text": {
                "tag": "lark_md",
                "content": f"{icon} **{en_label}**",
                "i18n_content": _i18n(
                    f"{icon} **{en_label}**",
                    f"{icon} **{zh_label}**",
                ),
            },
        },
    ]

    if user_name:
        elements.append({
            "tag": "markdown",
            "content": f"by **{user_name}**",
        })

    if tool_name:
        elements.append({
            "tag": "markdown",
            "content": f"`{tool_name}`",
        })

    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": False,
            "locales": _LOCALES,
            "summary": _summary(f"{icon} {en_label}"),
        },
        "header": _build_header(
            header_status,
            title=(f"{icon} {en_label}", f"{icon} {zh_label}"),
        ),
        "body": {"elements": elements},
    }


def build_clarify_submitted_card(
    *,
    question: str,
    selected: str,
    clarify_id: str = "",
) -> dict[str, Any]:
    """构建 Clarify 已提交态卡片（State 2: Submitted / Soft Lock）.

    三态卡片设计 — 已提交态（软锁定）:
      - 标题: lock_outlined 图标 + 问题文本
      - 用户选择内容
      - "已提交，等待确认..." 提示
      - 「重试提交」按钮：重新发送同一选择（非重新选择）

    Args:
        question: 原始问题文本
        selected: 用户选择的文本
        clarify_id: 唯一标识，用于重试回调路由
    """
    en_selected, zh_selected = _T["clarify_selected"]
    en_sel_label = en_selected.format(selected)
    zh_sel_label = zh_selected.format(selected)

    en_submitted, zh_submitted = _T["clarify_submitted"]
    en_retry, zh_retry = _T["clarify_retry"]

    elements: list[dict] = [
        {
            "tag": "div",
            "icon": {
                "tag": "standard_icon",
                "token": "lock_outlined",
                "size": "20px 20px",
                "color": "orange",
            },
            "text": {
                "tag": "lark_md",
                "content": f"**{question}**",
            },
        },
        {
            "tag": "div",
            "icon": {
                "tag": "standard_icon",
                "token": "lock_outlined",
                "size": "16px 16px",
                "color": "orange",
            },
            "text": {
                "tag": "lark_md",
                "content": en_sel_label,
                "i18n_content": _i18n(en_sel_label, zh_sel_label),
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"*{en_submitted}*",
                "i18n_content": _i18n(f"*{en_submitted}*", f"*{zh_submitted}*"),
            },
        },
        {
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": en_retry,
                    "i18n_content": _i18n(en_retry, zh_retry),
                },
                "type": "primary",
                "behaviors": [{
                    "type": "callback",
                    "value": {
                        "hermes_clarify_action": "retry_submit",
                        "clarify_id": clarify_id,
                    },
                }],
            }],
        },
    ]

    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {
            "streaming_mode": False,
            "locales": _LOCALES,
            "summary": _summary(selected or question),
        },
        "header": _build_header(
            "clarify",
            title=("Clarification Submitted", "澄清已提交"),
            subtitle=("Waiting for confirmation", "等待确认"),
        ),
        "body": {"elements": elements},
    }
    return card


def build_clarify_confirmed_card(
    *,
    question: str,
    selected: str,
) -> dict[str, Any]:
    """构建 Clarify 已确认态卡片（State 3: Confirmed / Hard Lock）.

    三态卡片设计 — 已确认态（硬锁定）:
      - 标题: resolve_filled 图标 + 问题文本
      - 用户选择内容
      - "已确认" 文本
      - 无操作按钮（由服务端更新卡片至此态）

    Args:
        question: 原始问题文本
        selected: 用户选择的文本
    """
    en_selected, zh_selected = _T["clarify_selected"]
    en_sel_label = en_selected.format(selected)
    zh_sel_label = zh_selected.format(selected)

    en_confirmed, zh_confirmed = _T["clarify_confirmed"]

    elements: list[dict] = [
        {
            "tag": "div",
            "icon": {
                "tag": "standard_icon",
                "token": "resolve_filled",
                "size": "20px 20px",
                "color": "green",
            },
            "text": {
                "tag": "lark_md",
                "content": f"**{question}**",
            },
        },
        {
            "tag": "div",
            "icon": {
                "tag": "standard_icon",
                "token": "resolve_filled",
                "size": "16px 16px",
                "color": "green",
            },
            "text": {
                "tag": "lark_md",
                "content": en_sel_label,
                "i18n_content": _i18n(en_sel_label, zh_sel_label),
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": en_confirmed,
                "i18n_content": _i18n(en_confirmed, zh_confirmed),
            },
        },
    ]

    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {
            "streaming_mode": False,
            "locales": _LOCALES,
            "summary": _summary(selected or question),
        },
        "header": _build_header(
            "completed",
            title=("Clarification Confirmed", "澄清已确认"),
            subtitle=("Selection locked", "选择已锁定"),
        ),
        "body": {"elements": elements},
    }
    return card
