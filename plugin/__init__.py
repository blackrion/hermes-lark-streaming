"""Plugin entry point — register(ctx) for Hermes plugin system.

Local deployment note:
- This installation intentionally keeps ``config.yaml`` manually edited to
  preserve comments, formatting, and existing Unicode/text representation.
- On registration, the plugin validates that ``plugins.enabled`` contains
  ``hermes-lark-streaming`` and that a top-level ``hermes_lark_streaming``
  section exists, but it does not rewrite ``config.yaml`` with ``yaml.dump``.

On unregistration:
- Does not mutate ``config.yaml``. Remove the config block and enabled entry
  manually if uninstalling this local plugin copy.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .. import __version__

if TYPE_CHECKING:
    from hermes_cli.plugins import PluginContext

_logger = logging.getLogger("hermes_lark_streaming")


def _get_hermes_config_path() -> Path:
    """动态获取 Hermes 配置文件路径（从 config/reader.py 复用）."""
    from ..config.reader import _get_hermes_config_path as _get_path
    return _get_path()


_PLUGIN_NAME = "hermes-lark-streaming"

# Default hermes_lark_streaming config injected into config.yaml on first load
_DEFAULT_STREAMING_CONFIG: dict[str, Any] = {
    "enabled": True,
    "linear": True,
    "panel_expanded": False,
    "streaming_panel_expanded": False,
    "print_strategy": "delay",
    "flush_interval_ms": 100,
    "card_ttl_sec": 600,
    "max_tool_steps": 20,
    "max_reasoning_rounds": 20,
    "inject_time": False,
    "footer": {
        "fields": [
            ["status", "elapsed", "model", "cost", "compression_exhausted"],
        ],
        "show_label": False,
    },
}


def _backup_config() -> None:
    """Back up config.yaml before first modification.

    Backup filename format: config.yaml.YYYYMMDD_HHMMSS.hermes-lark-streaming
    Only creates one backup per plugin installation (skips if a backup already exists).
    """
    # 每次都动态读取 HERMES_HOME，支持多 Profile 场景
    config_path = _get_hermes_config_path()
    if not config_path.exists():
        return

    # Check if a backup for this plugin already exists
    backup_pattern = f"config.yaml.*.{_PLUGIN_NAME}"
    parent = config_path.parent
    existing_backups = list(parent.glob(backup_pattern))
    if existing_backups:
        _logger.info("Backup already exists: %s, skipping", existing_backups[0].name)
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"config.yaml.{timestamp}.{_PLUGIN_NAME}"
    backup_path = parent / backup_name

    try:
        shutil.copy2(config_path, backup_path)
        _logger.info("Backed up config.yaml to %s", backup_path)
    except Exception:
        _logger.exception("Failed to back up config.yaml to %s", backup_path)


def _prepare_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Pre-process config dict before YAML dump.

    Handles nested dicts recursively. Footer fields are kept as-is
    (2D array for row layout) so the YAML output preserves the
    visual row structure.
    """
    result: dict[str, Any] = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            result[k] = _prepare_config(v)
        else:
            result[k] = v
    return result


def _ensure_streaming_config() -> None:
    """Validate config.yaml without rewriting it.

    The upstream plugin auto-injects defaults with ``yaml.dump``.  On this
    Hermes installation config.yaml contains comments and carefully preserved
    formatting, so activation is handled by a manual surgical edit instead.
    """
    config_path = _get_hermes_config_path()
    if not config_path.exists():
        _logger.warning("config.yaml not found at %s; cannot validate hermes_lark_streaming config", config_path)
        return

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        missing: list[str] = []

        if "hermes_lark_streaming" not in raw:
            missing.append("top-level hermes_lark_streaming")

        plugins = raw.get("plugins")
        enabled = plugins.get("enabled") if isinstance(plugins, dict) else None
        if not isinstance(enabled, list) or _PLUGIN_NAME not in enabled:
            missing.append("plugins.enabled entry hermes-lark-streaming")

        if missing:
            _logger.warning(
                "hermes-lark-streaming config validation failed; not mutating config.yaml. Missing: %s",
                ", ".join(missing),
            )
        else:
            _logger.info("hermes-lark-streaming config present; config.yaml left unchanged")
    except Exception:
        _logger.exception("Failed to validate hermes_lark_streaming config in config.yaml")


def _cleanup_config() -> None:
    """No-op cleanup to avoid round-tripping config.yaml through yaml.dump."""
    _logger.info(
        "hermes-lark-streaming cleanup skipped; config.yaml is managed manually on this installation"
    )


def register(ctx: "PluginContext") -> None:
    """Register hermes-lark-streaming as a Hermes plugin.

    Applies runtime monkey patches to GatewayRunner, AIAgent, and
    Scheduler so that streaming CardKit v2.0 cards are sent during
    Feishu conversations — no source file modification required.
    """
    _ensure_streaming_config()

    # ── Diagnostic: log key config for troubleshooting ──
    try:
        from ..config import Config
        _diag_cfg = Config()
        _logger.info(
            "hermes-lark-streaming v%s: config diagnostic — "
            "enabled=%s linear=%s gateway_cards=%s inject_time=%s "
            "panel_expanded=%s streaming_panel_expanded=%s print_strategy=%s "
            "flush_interval=%sms card_ttl=%ss footer_fields=%s show_label=%s",
            __version__,
            _diag_cfg.enabled,
            _diag_cfg.linear,
            _diag_cfg.gateway_cards,
            _diag_cfg.inject_time,
            _diag_cfg.panel_expanded,
            _diag_cfg.streaming_panel_expanded,
            _diag_cfg.print_strategy,
            _diag_cfg.flush_interval_ms,
            _diag_cfg.card_duration_sec,
            _diag_cfg.footer_fields,
            _diag_cfg.footer_show_label,
        )
    except Exception:
        _logger.debug("config diagnostic log failed", exc_info=True)

    _logger.info("hermes-lark-streaming v%s: applying runtime patches...", __version__)
    try:
        from ..patching import apply_patches

        apply_patches()
        _logger.info("hermes-lark-streaming v%s: patches applied (check logs for per-module status)", __version__)
    except Exception:
        _logger.exception("hermes-lark-streaming v%s: failed to apply patches", __version__)

    # ── Pre-warm FeishuClient ──
    # Initialize the Feishu API client at plugin registration time instead of
    # lazily on the first message.  This eliminates ~50-100ms latency on the
    # first card creation, improving the time-to-first-paint for users.
    try:
        from ..controller import get_controller
        import asyncio

        ctrl = get_controller()
        if ctrl.enabled:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ctrl._ensure_init())
                _logger.info("hermes-lark-streaming v%s: FeishuClient pre-warm scheduled", __version__)
            else:
                _logger.debug("hermes-lark-streaming v%s: event loop not running, skipping pre-warm", __version__)
    except Exception:
        _logger.debug("hermes-lark-streaming v%s: FeishuClient pre-warm skipped", __version__, exc_info=True)

    # ── v1.1.0: Register /aowen command hook (Task 3.7) ──
    try:
        from ..aowen import handle_pre_gateway_dispatch
        ctx.register_hook("pre_gateway_dispatch", handle_pre_gateway_dispatch)
        _logger.info("hermes-lark-streaming v%s: /aowen commands registered (help, status, monitor)", __version__)
    except Exception:
        _logger.debug("hermes-lark-streaming v%s: /aowen hook registration skipped", __version__, exc_info=True)


def unregister(ctx: "PluginContext") -> None:
    """Unregister hermes-lark-streaming.

    Cleans up the injected hermes_lark_streaming config from config.yaml.
    """
    _cleanup_config()
    # Clear controller sessions
    try:
        from ..controller import get_controller
        ctrl = get_controller()
        ctrl._sessions.clear()
    except Exception:
        pass
    _logger.info("hermes-lark-streaming: unregistered")
