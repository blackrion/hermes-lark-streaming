<h1 align="center">hermes-lark-streaming</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Project-Vibe%20Coding-ff69b4" alt="Vibe Coding">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-4caf50.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776AB.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/version-1.2.0-ff9800.svg" alt="Version">
</p>

<p align="center">
<a href="https://github.com/blackrion"><img src="https://img.shields.io/badge/GitHub-blackrion-181717?logo=github&logoColor=white" alt="GitHub"></a>
</p>

<p align="center">
English | <a href="README.zh-CN.md">中文版</a>
</p>

Feishu/Lark CardKit v2.0 streaming cards plugin for Hermes Agent — real-time AI response display with typewriter effect, unified collapsible panel, interactive approval & clarification cards, and more.

> Based on [Aowen-Nowor/hermes-lark-streaming](https://github.com/Aowen-Nowor/hermes-lark-streaming) v1.1.3 (originally derived from [Cheerwhy/hermes-lark-streaming](https://github.com/Cheerwhy/hermes-lark-streaming) v0.7.0), with features ported from [larksuite/openclaw-lark](https://github.com/larksuite/openclaw-lark) (MIT, ByteDance) and customizations inspired by [baileyh8/hermes-feishu-streaming-card](https://github.com/baileyh8/hermes-feishu-streaming-card).
>
> 📝 **Personal fork** — maintained by [blackrion](https://github.com/blackrion) for self-use. All upstream MIT license terms are preserved.

---

## Features

### Streaming Reply Cards

- **Real-time typewriter effect** — answer text streams in via CardKit `stream_element` API
- **Unified collapsible panel** — reasoning rounds and tool calls displayed chronologically in a single panel, interleaving as they actually occurred
- **Status-aware card header** — header changes color and text by state: thinking (blue), streaming (indigo), completed (green), error (red), approval (orange)
- **Two-line footer** — line 1: status · elapsed · model; line 2: tokens · cache · context · cost

### Interactive Approval Cards

When the Agent attempts to execute a dangerous command (e.g., `rm`, `git push --force`), an interactive approval card is sent:

- **Command preview** in a fenced code block (truncated to 3000 chars)
- **Four approval buttons**: ✅ Allow Once · 🔁 This Session · ⭐ Always · ❌ Deny
- **Resolved state**: after clicking, the card updates to show the decision (approved/denied) with the user's name
- Ported from [openclaw-lark](https://github.com/larksuite/openclaw-lark) `buildConfirmCard()` (MIT, ByteDance)

### Interactive Clarification Cards

When the Agent uses the `clarify` tool to ask a question, a three-state interactive card is sent:

- **State 1 — Pending**: question text + choice list + dropdown select + text input (500 char limit)
- **State 2 — Submitted**: soft-lock showing the user's selection + retry button
- **State 3 — Confirmed**: hard-lock after Hermes processes the answer, showing final selection

### Gateway Message Cards

All non-AI messages from the gateway (slash commands, auth, errors, session lifecycle) are converted to styled CardKit 2.0 cards with category-aware headers.

### Cron Delivery Cards

Scheduled task results are delivered as styled cards instead of plain text.

### Additional Features

- **Markdown table spacing** — proper spacing between headings, tables, and code blocks
- **Tool parameter redaction** — sensitive headers (`-H Authorization: ...`), URLs, and file paths in tool calls are redacted for display
- **CardKit API fail-fast** — API errors are detected and logged immediately instead of silently failing
- **Cache hit rate** — footer shows `cache_read/cache_write (hit%)` using the correct formula
- **Flush-on-conflict** — flush controller detects version conflicts and recovers automatically
- **Invalid image key cleanup** — broken image references are stripped before rendering

---

## Quick Start

### Prerequisites

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.17.0+ (running, with Feishu platform configured)
- Hermes CLI with plugin system support (`hermes plugins` command available)

### Installation

```bash
# GitHub (SSH)
hermes plugins install git@github.com:blackrion/hermes-lark-streaming.git
# GitHub (HTTPS)
hermes plugins install https://github.com/blackrion/hermes-lark-streaming
```

Enter `Y` when prompted to enable the plugin, then restart the gateway:

```bash
hermes gateway restart
```

### Update

```bash
hermes plugins update hermes-lark-streaming
hermes gateway restart
```

### Uninstallation

```bash
# 1. Clean up injected config (while plugin code is still available)
HERMES_PYTHON=$(python3 ~/.hermes/plugins/hermes-lark-streaming/__main__.py python)
$HERMES_PYTHON ~/.hermes/plugins/hermes-lark-streaming/__main__.py cleanup

# 2. Remove plugin
hermes plugins uninstall hermes-lark-streaming

# 3. Restart gateway
hermes gateway restart
```

### Verify Installation

```bash
hermes plugins list
HERMES_PYTHON=$(python3 ~/.hermes/plugins/hermes-lark-streaming/__main__.py python)
$HERMES_PYTHON ~/.hermes/plugins/hermes-lark-streaming/__main__.py status
$HERMES_PYTHON ~/.hermes/plugins/hermes-lark-streaming/__main__.py doctor
```

---

## Configuration

All settings go under the `hermes_lark_streaming:` section in `~/.hermes/config.yaml`. The plugin auto-injects defaults on first load.

```yaml
hermes_lark_streaming:
  enabled: true                # Enable streaming cards
  linear: true                 # Single-card in-place update (unified panel architecture)
  panel_expanded: false        # Keep panels expanded in completed cards
  streaming_panel_expanded: false  # Keep panels expanded during streaming
  print_strategy: delay        # "fast" (instant) or "delay" (smoother typewriter, default)
  flush_interval_ms: 100       # Card refresh interval in ms (70–2000, default 100)
  card_ttl_sec: 600            # Card alive detection timeout (seconds)
  max_tool_steps: 20           # Max tool steps shown in panel (1–100)
  max_reasoning_rounds: 20     # Max reasoning rounds shown in panel (1–100)

  footer:
    show_label: false          # Show field labels (Model, Tokens, etc.)
    # Default: two-line layout
    # fields:
    #   - [status, elapsed, model]
    #   - [tokens, cache, context, cost, compression_exhausted]
    #
    # Available fields:
    #   status      — Reply status (Completed / Error / Stopped)
    #   elapsed     — AI response elapsed time
    #   model       — Model name used
    #   cost        — Estimated cost ($0.023 est. / $0.023 actual / Free)
    #   tokens      — Token usage (↑ input ↓ output 💭 reasoning)
    #   cache       — Cache hit rate (cache_read/cache_write hit%)
    #   context     — Context window usage (used/total percentage)
    #   compression_exhausted — Context window is full (⚠ Context Full)
    #   api_calls   — Number of API calls in this session
    #   history_offset — Conversation history offset
```

### /aowen Commands

Send `/aowen` commands in Feishu, the plugin replies with cards directly:

| Command                | Description                                            |
| ---------------------- | ------------------------------------------------------ |
| `/aowen help`          | Show all available commands                            |
| `/aowen status`        | Show plugin status + current config                   |
| `/aowen monitor`       | Show metrics dashboard (cards, API calls, errors)      |
| `/aowen monitor reset` | Reset metrics counters                                 |
| `/aowen config reload` | Apply config changes immediately without restart        |

### Feishu Credentials

The plugin reuses Hermes's existing Feishu credentials — no separate configuration needed. If the Hermes Feishu channel works, the plugin works too.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Hermes Agent                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │              GatewayRunner / AIAgent               │  │
│  │   (patched at runtime — no source modification)    │  │
│  └──────────────┬───────────────────────┬────────────┘  │
│                 │                       │                │
│     ┌───────────▼──────────┐  ┌────────▼─────────┐      │
│     │   FeishuAdapter      │  │   Cron Scheduler  │      │
│     │ .send() → intercepted │  │ .deliver → card    │      │
│     │ .send_clarify() →     │  └──────────────────┘      │
│     │   interactive card   │                            │
│     │ .send_exec_approval() │                            │
│     │   → CardKit 2.0 card  │                            │
│     └───────────┬──────────┘                            │
│                 │                                        │
│  ┌──────────────▼────────────────────────────────────┐  │
│     │              Plugin (hermes-lark-streaming)       │
│     │                                                   │
│     │  ┌─────────────┐  ┌──────────────┐  ┌──────────┐ │
│     │  │ Controller   │  │  CardKit     │  │ Patching │ │
│     │  │ (sessions,   │  │  (builders)  │  │ (monkey  │ │
│     │  │  flush, seal)│  │              │  │  patch)  │ │
│     │  └──────┬──────┘  └──────┬───────┘  └──────────┘ │
│     │         │                │                        │
│     │  ┌──────▼──────────────────────────────┐         │
│     │  │         FeishuClient                  │         │
│     │  │  (CardKit v2.0 API: stream_element,  │         │
│     │  │   batch_update, close_streaming,     │         │
│     │  │   cardkit_update, create_card)       │         │
│     │  └──────────────────────────────────────┘         │
│     └───────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Runtime monkey patching** — no Hermes source files modified; all patches applied via `FeishuAdapter.method = wrapper(FeishuAdapter.method)`
- **Unified panel architecture** — single `collapsible_panel` holds all reasoning/tool steps, reducing card elements from 50+ to 4
- **CardKit 2.0 streaming** — uses `stream_element` for real-time text, `batch_update` for panel, `close_streaming` + `cardkit_update` for seal
- **Three-state interactive cards** — clarify and approval cards maintain pending → submitted → confirmed states
- **Fallback safety** — every card operation falls back to plain text if CardKit API fails

---

## Acknowledgments

- [Aowen-Nowor/hermes-lark-streaming](https://github.com/Aowen-Nowor/hermes-lark-streaming) — upstream plugin base (MIT)
- [Cheerwhy/hermes-lark-streaming](https://github.com/Cheerwhy/hermes-lark-streaming) — original plugin (MIT)
- [larksuite/openclaw-lark](https://github.com/larksuite/openclaw-lark) — official Feishu plugin, features ported under MIT license
- [baileyh8/hermes-feishu-streaming-card](https://github.com/baileyh8/hermes-feishu-streaming-card) — header/status design inspiration
