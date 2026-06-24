"""Tests for Approval interactive card feature.

Tests the card builders (build_approval_card, build_approval_resolved_card)
and the monkey-patch wrapper (_wrap_feishu_adapter_send_exec_approval).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_lark_streaming.cardkit import (
    build_approval_card,
    build_approval_resolved_card,
)


# ── build_approval_card (Pending state) ──


class TestBuildApprovalCard:
    """Test build_approval_card with command and description."""

    def test_schema_2_and_streaming_false(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm -rf /tmp/test",
            description="dangerous command",
            approval_id=1,
        )
        assert card["schema"] == "2.0"
        assert card["config"]["streaming_mode"] is False

    def test_header_is_approval_status(self) -> None:
        card = build_approval_card(
            tool_name="git",
            command="git push --force",
            approval_id=2,
        )
        header = card["header"]
        assert header["template"] == "orange"

    def test_tool_name_displayed_with_shield_icon(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm -rf /tmp/test",
            approval_id=3,
        )
        elements = card["body"]["elements"]
        assert elements[0]["tag"] == "div"
        assert elements[0]["icon"]["token"] == "shield_color"
        assert elements[0]["icon"]["color"] == "orange"
        assert "rm" in elements[0]["text"]["content"]

    def test_command_preview_in_code_block(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm -rf /tmp/test",
            approval_id=4,
        )
        elements = card["body"]["elements"]
        md_el = next(e for e in elements if e.get("tag") == "markdown" and "```" in e.get("content", ""))
        assert "rm -rf /tmp/test" in md_el["content"]

    def test_long_command_truncated(self) -> None:
        long_cmd = "echo " + "x" * 4000
        card = build_approval_card(
            tool_name="echo",
            command=long_cmd,
            approval_id=5,
        )
        elements = card["body"]["elements"]
        md_el = next(e for e in elements if e.get("tag") == "markdown" and "```" in e.get("content", ""))
        assert "..." in md_el["content"]
        assert len(md_el["content"]) < 4000

    def test_description_with_reason_label(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm -rf /tmp",
            description="destructive operation",
            approval_id=6,
        )
        elements = card["body"]["elements"]
        md_el = next(e for e in elements if e.get("tag") == "markdown" and "Reason" in e.get("content", ""))
        assert "destructive operation" in md_el["content"]

    def test_hr_separator_before_buttons(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm /tmp/file",
            approval_id=7,
        )
        elements = card["body"]["elements"]
        hr_indices = [i for i, e in enumerate(elements) if e.get("tag") == "hr"]
        assert len(hr_indices) >= 1

    def test_four_approval_buttons_present(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm /tmp/file",
            approval_id=8,
        )
        elements = card["body"]["elements"]
        buttons = []
        for el in elements:
            if el.get("tag") == "column_set":
                for col in el.get("columns", []):
                    for sub in col.get("elements", []):
                        if sub.get("tag") == "button":
                            buttons.append(sub)
        assert len(buttons) == 4
        actions = [b["behaviors"][0]["value"]["hermes_action"] for b in buttons]
        assert "approve_once" in actions
        assert "approve_session" in actions
        assert "approve_always" in actions
        assert "deny" in actions

    def test_deny_button_is_danger_type(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm /tmp/file",
            approval_id=9,
        )
        elements = card["body"]["elements"]
        deny_btn = None
        for el in elements:
            if el.get("tag") == "column_set":
                for col in el.get("columns", []):
                    for sub in col.get("elements", []):
                        if sub.get("tag") == "button" and sub["behaviors"][0]["value"]["hermes_action"] == "deny":
                            deny_btn = sub
        assert deny_btn is not None
        assert deny_btn["type"] == "danger"

    def test_approve_once_button_is_primary_type(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm /tmp/file",
            approval_id=10,
        )
        elements = card["body"]["elements"]
        approve_btn = None
        for el in elements:
            if el.get("tag") == "column_set":
                for col in el.get("columns", []):
                    for sub in col.get("elements", []):
                        if sub.get("tag") == "button" and sub["behaviors"][0]["value"]["hermes_action"] == "approve_once":
                            approve_btn = sub
        assert approve_btn is not None
        assert approve_btn["type"] == "primary"

    def test_approval_id_in_callback_value(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm /tmp/file",
            approval_id=42,
        )
        elements = card["body"]["elements"]
        for el in elements:
            if el.get("tag") == "column_set":
                for col in el.get("columns", []):
                    for sub in col.get("elements", []):
                        if sub.get("tag") == "button":
                            val = sub["behaviors"][0]["value"]
                            assert val["approval_id"] == 42

    def test_no_command_skips_code_block(self) -> None:
        card = build_approval_card(
            tool_name="custom_tool",
            description="some reason",
            approval_id=11,
        )
        elements = card["body"]["elements"]
        code_blocks = [e for e in elements if e.get("tag") == "markdown" and "```" in e.get("content", "")]
        assert len(code_blocks) == 0

    def test_no_description_skips_reason(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm /tmp",
            approval_id=12,
        )
        elements = card["body"]["elements"]
        reason_els = [e for e in elements if e.get("tag") == "markdown" and "Reason" in e.get("content", "")]
        assert len(reason_els) == 0

    def test_summary_uses_tool_name(self) -> None:
        card = build_approval_card(
            tool_name="rm",
            command="rm /tmp/file",
            approval_id=13,
        )
        assert card["config"]["summary"]["content"] == "rm"


# ── build_approval_resolved_card (Resolved state) ──


class TestBuildApprovalResolvedCard:
    """Test build_approval_resolved_card for all choice types."""

    @pytest.mark.parametrize("choice,expected_icon", [
        ("once", "✅"),
        ("session", "✅"),
        ("always", "✅"),
        ("deny", "❌"),
    ])
    def test_icon_based_on_choice(self, choice: str, expected_icon: str) -> None:
        card = build_approval_resolved_card(choice=choice, user_name="tester")
        elements = card["body"]["elements"]
        assert expected_icon in elements[0]["text"]["content"]

    def test_deny_uses_error_header_status(self) -> None:
        card = build_approval_resolved_card(choice="deny", user_name="tester")
        # "error" header template should be red
        assert card["header"]["template"] == "red"

    def test_approve_uses_completed_header_status(self) -> None:
        card = build_approval_resolved_card(choice="once", user_name="tester")
        # "completed" header template should be green
        assert card["header"]["template"] == "green"

    def test_user_name_displayed(self) -> None:
        card = build_approval_resolved_card(choice="once", user_name="Alice")
        elements = card["body"]["elements"]
        user_el = next(e for e in elements if e.get("tag") == "markdown" and "Alice" in e.get("content", ""))
        assert user_el is not None

    def test_tool_name_displayed(self) -> None:
        card = build_approval_resolved_card(choice="once", user_name="Alice", tool_name="rm")
        elements = card["body"]["elements"]
        tool_el = next(e for e in elements if e.get("tag") == "markdown" and "rm" in e.get("content", ""))
        assert tool_el is not None

    def test_schema_2_and_streaming_false(self) -> None:
        card = build_approval_resolved_card(choice="deny", user_name="tester")
        assert card["schema"] == "2.0"
        assert card["config"]["streaming_mode"] is False

    def test_label_mapping_once(self) -> None:
        card = build_approval_resolved_card(choice="once", user_name="tester")
        elements = card["body"]["elements"]
        assert "Approved Once" in elements[0]["text"]["content"]

    def test_label_mapping_deny(self) -> None:
        card = build_approval_resolved_card(choice="deny", user_name="tester")
        elements = card["body"]["elements"]
        assert "Denied" in elements[0]["text"]["content"]

    def test_unknown_choice_fallback(self) -> None:
        card = build_approval_resolved_card(choice="unknown", user_name="tester")
        elements = card["body"]["elements"]
        assert "Resolved" in elements[0]["text"]["content"]


# ── _wrap_feishu_adapter_send_exec_approval ──


class TestWrapSendExecApproval:
    """Test the send_exec_approval monkey-patch wrapper."""

    @pytest.mark.asyncio
    async def test_fallback_when_controller_not_available(self) -> None:
        """When controller is not available, should fall back to original."""
        from hermes_lark_streaming.patching import _wrap_feishu_adapter_send_exec_approval

        orig = AsyncMock(return_value="original_result")
        wrapper = _wrap_feishu_adapter_send_exec_approval(orig)

        mock_self = MagicMock()
        mock_self._approval_counter = iter([1])

        with patch("hermes_lark_streaming.controller.get_controller") as mock_get:
            mock_ctrl = MagicMock()
            mock_ctrl.enabled = False
            mock_get.return_value = mock_ctrl

            result = await wrapper(
                mock_self, "chat123", "rm -rf /tmp", "session_key",
                description="test", metadata=None
            )
            assert result == "original_result"
            orig.assert_called_once()

    @pytest.mark.asyncio
    async def test_card_sent_when_controller_available(self) -> None:
        """When controller is available, should send CardKit 2.0 card."""
        from hermes_lark_streaming.patching import _wrap_feishu_adapter_send_exec_approval

        orig = AsyncMock(return_value="original_result")
        wrapper = _wrap_feishu_adapter_send_exec_approval(orig)

        mock_self = MagicMock()
        mock_self._approval_counter = iter([1])
        mock_self._approval_state = {}

        mock_ctrl = MagicMock()
        mock_ctrl.enabled = True
        mock_ctrl._client_ok.return_value = True
        mock_ctrl._client.send_card_to_chat = AsyncMock(return_value="card_msg_123")

        with patch("hermes_lark_streaming.controller.get_controller", return_value=mock_ctrl):
            result = await wrapper(
                mock_self, "chat123", "rm -rf /tmp", "session_key",
                description="dangerous", metadata=None
            )

            assert result is not None
            mock_ctrl._client.send_card_to_chat.assert_called_once()
            # Verify approval state was stored
            assert 1 in mock_self._approval_state
            assert mock_self._approval_state[1]["session_key"] == "session_key"
