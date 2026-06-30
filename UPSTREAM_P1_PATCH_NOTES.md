# 上游 P1 修复补丁说明 — hermes-lark-streaming fork

> 分析对象：upstream commit `3fd7a08` (v1.3.1) + `7dca87a` (v1.3.2) 中的 P1 级修复
> Fork 分支：`sync/upstream-p0-p1`（基于 `0ae8d70` 分叉点）
> 生成时间：2026-06-30

---

## 关于 "inspect.signature 崩溃" 的说明

任务描述提到 7dca87a 包含 "inspect.signature 崩溃" 修复。经核实，7dca87a 的 diff 中**不包含**任何 inspect.signature 相关改动。该修复实际是 commit `ae86877`（"fix: run_conversation wrapper 兼容有/无 persist_user_timestamp 的 Hermes 版本"），它在 `0ae8d70`（我们的分叉点）**之前**已合并。

我们的 fork 已经包含此修复（`patching/__init__.py` 第 612-616 行的 `inspect.signature(_orig_method).parameters` 检测逻辑）。**无需额外操作。**

---

## Commit 3fd7a08 — v1.3.1 补充修复

### 修复 1：_gateway_cards 内存泄漏（F-08）

- **文件**：`patching/adapter.py`
- **修复逻辑**：`_register_gateway_card()` 向 `_gateway_cards` 字典添加条目但从不清理（`_unregister_gateway_card` 从未在生产代码调用）。修复方案：添加 500 条容量上限 + `registered_at` 时间戳 + 超限时清理最旧 20%。
- **我们代码中对应的当前代码**（`patching/adapter.py` 第 262-275 行）：

```python
def _register_gateway_card(card_msg_id: str, *, chat_id: str, card_id: str | None, category: str) -> None:
    """Register a gateway card so edit_message can update it later."""
    if not card_msg_id:
        return
    with _gateway_cards_lock:
        _gateway_cards[card_msg_id] = {
            "chat_id": chat_id,
            "card_id": card_id,
            "category": category,
        }
    _logger.debug(
        "registered gateway card: msg_id=%s card_id=%s category=%s",
        card_msg_id[:12], (card_id or "?")[:12], category,
    )
```

- **需要改成**：

```python
def _register_gateway_card(card_msg_id: str, *, chat_id: str, card_id: str | None, category: str) -> None:
    """Register a gateway card so edit_message can update it later.

    v1.3.1 fix: Added capacity limit (500 entries) to prevent unbounded
    memory growth. When the limit is exceeded, oldest entries are pruned.
    """
    if not card_msg_id:
        return
    with _gateway_cards_lock:
        _gateway_cards[card_msg_id] = {
            "chat_id": chat_id,
            "card_id": card_id,
            "category": category,
            "registered_at": time.time(),
        }
        # v1.3.1: prune oldest entries when over capacity
        _GATEWAY_CARDS_MAX = 500
        if len(_gateway_cards) > _GATEWAY_CARDS_MAX:
            excess = len(_gateway_cards) - _GATEWAY_CARDS_MAX + (_GATEWAY_CARDS_MAX // 5)
            sorted_keys = sorted(_gateway_cards, key=lambda k: _gateway_cards[k].get("registered_at", 0))
            for k in sorted_keys[:excess]:
                _gateway_cards.pop(k, None)
            _logger.debug("HLS: _gateway_cards pruned %d entries (was %d)", excess, len(_gateway_cards) + excess)
    _logger.debug(
        "registered gateway card: msg_id=%s card_id=%s category=%s",
        card_msg_id[:12], (card_id or "?")[:12], category,
    )
```

- **冲突风险**：低。**注意**：`patching/adapter.py` 当前**没有** `import time`（仅有 `asyncio`、`logging`），需要额外在顶部添加 `import time`。

---

### 修复 2：/new /reset 确认消息被抑制（EphemeralReply 直通）

- **文件**：`patching/adapter.py`
- **修复逻辑**：`_intercepted_send` 中 `card_sent` 守卫会抑制所有文本发送，包括 `/new`、`/reset` 等命令的 `EphemeralReply` 确认消息。修复：在非字符串守卫之前，先检查 `isinstance(content, EphemeralReply)`，如果是则直接透传给 `orig_send`。
- **我们代码中对应的当前代码**（`patching/adapter.py` 第 82-87 行）：

```python
async def _intercepted_send(self_feishu, chat_id, content, reply_to=None, metadata=None, **kwargs):
    # ── Agent path: handle non-string sends ──
    if not isinstance(content, str):
        return await orig_send(self_feishu, chat_id, content, reply_to=reply_to, metadata=metadata, **kwargs)
```

- **需要改成**（在 `if not isinstance(content, str)` 之前插入）：

```python
async def _intercepted_send(self_feishu, chat_id, content, reply_to=None, metadata=None, **kwargs):
    # ── EphemeralReply passthrough (v1.3.1 fix) ──
    # Gateway-internal slash commands (e.g. /new, /reset) return
    # EphemeralReply instances. These must NEVER be suppressed by the
    # card_sent guard.
    try:
        from gateway.platforms.base import EphemeralReply
        if isinstance(content, EphemeralReply):
            return await orig_send(self_feishu, chat_id, content, reply_to=reply_to, metadata=metadata, **kwargs)
    except (ImportError, AttributeError):
        pass

    # ── Agent path: handle non-string sends ──
    if not isinstance(content, str):
        return await orig_send(self_feishu, chat_id, content, reply_to=reply_to, metadata=metadata, **kwargs)
```

- **冲突风险**：低。插入位置清晰，不修改现有逻辑。

---

### 修复 3：FeishuAdapter import 路径（3 路径 fallback）

- **文件**：`patching/hermes_adapter.py`
- **修复逻辑**：`from gateway.platforms.feishu import FeishuAdapter` 在 Hermes v0.17.0 中失败。改为 3 路径 fallback：`hermes_plugins.feishu_platform.adapter` > `plugins.platforms.feishu.adapter` > `gateway.platforms.feishu`。
- **我们代码中对应的当前代码**：**已修复。** 我们的 fork 已有更完善的 `_resolve_feishu_adapter_class()`（第 98-141 行），包含 5 路径 fallback + `platform_registry` 查找 + `sys.modules` 扫描。
- **需要改成**：**无需改动。** 我们的实现更健壮，已覆盖上游修复的所有场景。
- **冲突风险**：无。

---

### 修复 4：_intercepting_send / _card_sending_send 参数名对齐

- **文件**：`patching/gateway.py`
- **修复逻辑**：Hermes `_send_with_retry` 用关键字参数 `self.send(chat_id=..., content=...)`，但 wrapper 用 `chat_id_send` / `content_text` → TypeError。修复：参数名对齐为 `chat_id` / `content`。
- **我们代码中对应的当前代码**（`patching/gateway.py` 第 759-772 行 + 第 898-953 行）：

**_intercepting_send**（第 759 行）：
```python
async def _intercepting_send(chat_id_send, content, **send_kwargs):
    ...
    chat_id_send[:12] if chat_id_send else "?",
    ...
    return await original_send(chat_id_send, content, **send_kwargs)
```

**_card_sending_send**（第 898 行）：
```python
async def _card_sending_send(chat_id_send, content_text, **send_kwargs):
    ...
    chat_id_send[:12] if chat_id_send else "?",
    len(content_text) if content_text else 0,
    if ctrl.enabled and content_text:
        cleaned = content_text
    ...
    await ctrl._do_cron_deliver(chat_id_send, cleaned.strip())
    ...
    return await original_send(chat_id_send, content_text, **send_kwargs)
```

- **需要改成**：
  - `_intercepting_send`：`chat_id_send` → `chat_id`（3 处）
  - `_card_sending_send`：`chat_id_send` → `chat_id`（5 处），`content_text` → `content`（6 处）
- **冲突风险**：低。纯机械替换，但需注意我们的 `_hls_bg_sending` 用的是布尔值（见下方修复）。

---

### 修复 5：配置读取容错（_to_int / _to_float）

- **文件**：`config/reader.py`
- **修复逻辑**：5 个数值配置项（`max_tool_steps`、`max_reasoning_rounds`、`print_step`、`flush_interval_ms`、`card_ttl_sec`）直接用 `int()` / `float()` 转换，非数字字符串导致 ValueError 崩溃。修复：新增 `_to_int` / `_to_float` 安全转换 helper。
- **我们代码中对应的当前代码**：

我们的 fork **没有** `print_step` 配置项（上游在 v1.3.0 后续 commit 中添加，我们的 fork 没有）。其余 4 项存在：

| 属性 | 行号 | 当前代码 |
|---|---|---|
| `max_tool_steps` | 第 112-113 行 | `val = sec.get("max_tool_steps", 20)` → `return max(1, min(100, int(val)))` |
| `max_reasoning_rounds` | 第 124-125 行 | `val = sec.get("max_reasoning_rounds", 20)` → `return max(1, min(100, int(val)))` |
| `flush_interval_ms` | 第 148 行 | `ms = float(sec.get("flush_interval_ms", 100))` |
| `card_duration_sec` | 第 194 行 | `return int(self._plugin_sec().get("card_ttl_sec", 600))` |

**注意**：我们的 `flush_interval_ms` 默认值是 `100`（上游改为 `200`，见 7dca87a docstring 修复）。

- **需要改成**：

1. 在 `config/reader.py` 第 35 行后（`_to_bool` 之后）添加 `_to_int` 和 `_to_float` helper：

```python
def _to_int(val: Any, default: int) -> int:
    """安全 int 转换，类型错误时返回 default。"""
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            _logger.warning("HLS: config value %r is not a valid int, using default %d", val, default)
            return default
    return default


def _to_float(val: Any, default: float) -> float:
    """安全 float 转换，类型错误时返回 default。"""
    if isinstance(val, bool):
        return float(val)
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            _logger.warning("HLS: config value %r is not a valid float, using default %f", val, default)
            return default
    return default
```

2. 需在模块顶部添加 `_logger`（我们的 fork 在 `reload()` 方法内局部创建 `_logger`，但模块级没有）。在 `import` 之后添加：
```python
import logging
_logger = logging.getLogger("hermes_lark_streaming")
```

3. 替换 4 处属性：
  - 第 112-113 行：`val = _to_int(sec.get("max_tool_steps", 20), default=20)` → `return max(1, min(100, val))`
  - 第 124-125 行：`val = _to_int(sec.get("max_reasoning_rounds", 20), default=20)` → `return max(1, min(100, val))`
  - 第 148 行：`ms = _to_float(sec.get("flush_interval_ms", 100), default=100.0)`
  - 第 194 行：`return _to_int(self._plugin_sec().get("card_ttl_sec", 600), default=600)`

- **冲突风险**：中。我们 fork 的 `config/reader.py` 结构与上游差异较大（没有 `print_step`、`_logger` 是局部的、`_load()` 没有 try/except）。需手动适配，不能直接 apply 上游 patch。

---

### 修复 6：_send_text_fallback 时序问题（F-09）

- **文件**：`controller/core.py`
- **修复逻辑**：`_do_linear_complete` 失败时调用 `_release_session_data` 清空 `session.text`，之后 `_send_text_fallback` 读到空文本。修复：在 `_do_linear_complete_with_fallback` 中提前快照 `fallback_text`，传给 `_send_text_fallback`。
- **我们代码中对应的当前代码**（`controller/core.py` 第 817-829 行）：

```python
async def _do_linear_complete_with_fallback(self, session: CardSession) -> None:
    """线性模式完成，卡片不可用时回退为文本回复."""
    try:
        result = await self._do_linear_complete(session)
        if not result:
            await self._send_text_fallback(session)
    except Exception:
        _logger.warning(...)
        await self._send_text_fallback(session)
```

第 831-841 行：
```python
async def _send_text_fallback(self, session: CardSession) -> None:
    ...
    text = session.error_message or session.text.display_text or ""
```

- **需要改成**：

```python
async def _do_linear_complete_with_fallback(self, session: CardSession) -> None:
    # Snapshot fallback text before _do_linear_complete potentially releases it
    _fallback_text = ""
    if session.error_message:
        _fallback_text = session.error_message
    elif session.unified_state and session.unified_state.answer_text:
        _fallback_text = session.unified_state.answer_text
    elif session.text and session.text.display_text:
        _fallback_text = session.text.display_text

    try:
        result = await self._do_linear_complete(session)
        if not result:
            await self._send_text_fallback(session, fallback_text=_fallback_text)
    except Exception:
        _logger.warning(...)
        await self._send_text_fallback(session, fallback_text=_fallback_text)

async def _send_text_fallback(self, session: CardSession, *, fallback_text: str = "") -> None:
    ...
    text = fallback_text or session.error_message or (session.text.display_text if session.text else "") or ""
```

- **冲突风险**：低。我们的 `_send_text_fallback` 签名和逻辑与上游分叉点一致，可直接应用。

---

## Commit 7dca87a — v1.3.2 全面审计修复

### 修复 7：_to_int 捕获 OverflowError + _to_float 拒绝 nan/inf

- **文件**：`config/reader.py`
- **修复逻辑**：`int(float('inf'))` 抛 OverflowError，`int(float('nan'))` 抛 ValueError — 都未捕获。`float('nan')` / `float('inf')` 是合法 Python float 但导致 `max()`/`min()` 比较失效。
- **依赖**：需先应用修复 5（`_to_int` / `_to_float` helper）。
- **需要改成**（在修复 5 添加的 helper 基础上）：

1. 顶部添加 `import math`
2. `_to_int` 的 `isinstance(val, float)` 分支改为：
```python
    if isinstance(val, float):
        try:
            return int(val)
        except (OverflowError, ValueError):
            _logger.warning("HLS: config float value %r cannot convert to int, using default %d", val, default)
            return default
```
3. `_to_float` 的 `isinstance(val, (int, float))` 分支改为：
```python
    if isinstance(val, (int, float)):
        result = float(val)
        if math.isnan(result) or math.isinf(result):
            _logger.warning("HLS: config float value %r is nan/inf, using default %f", val, default)
            return default
        return result
```
4. `_to_float` 的 `isinstance(val, str)` 分支改为：
```python
    if isinstance(val, str):
        try:
            result = float(val)
        except ValueError:
            _logger.warning("HLS: config value %r is not a valid float, using default %f", val, default)
            return default
        if math.isnan(result) or math.isinf(result):
            _logger.warning("HLS: config float value %r is nan/inf, using default %f", val, default)
            return default
        return result
```

- **冲突风险**：低。与修复 5 合并应用即可。

---

### 修复 8：配置文件读取捕获 OSError/UnicodeDecodeError

- **文件**：`config/reader.py`
- **修复逻辑**：`config_path.read_text()` 可能因权限不足、磁盘错误或编码问题失败。上游在 `_load()` 和 `_reload_cached()` 中 `yaml.safe_load` 外层已有 `try/except yaml.YAMLError`，新增 `except (OSError, UnicodeDecodeError)`。
- **我们代码中对应的当前代码**：我们的 fork 的 `_load()`（第 343-353 行）和 `_reload_cached()`（第 355-373 行）**没有**任何 try/except——直接 `read_text` + `yaml.safe_load`。
- **需要改成**：

`_load()`（第 348-353 行）：
```python
if config_path.exists():
    try:
        text = config_path.read_text(encoding="utf-8")
        self._raw = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        _logger.warning("HLS: config YAML syntax error in %s, using empty config", config_path)
        self._raw = {}
    except (OSError, UnicodeDecodeError):
        _logger.warning("HLS: config file read error in %s, using empty config", config_path)
        self._raw = {}
else:
    self._raw = {}
```

`_reload_cached()`（第 367-372 行）同理添加两层 except。

- **冲突风险**：中。我们 fork 的 `_load()` 结构更简单（无 try/except），需要完整包裹。

---

### 修复 9：_sessions 并发安全（_fire_and_forget Task 强引用）

- **文件**：`controller/core.py`
- **修复逻辑**：`asyncio` 仅对 Task 持弱引用，GC 可能在执行中回收 Task。修复：`self._pending_tasks: set[asyncio.Task]` 持强引用 + `add_done_callback(discard)`。
- **我们代码中对应的当前代码**（`controller/core.py` 第 116-124 行）：

```python
def _fire_and_forget(self, coro: Coroutine[Any, Any, Any], loop: asyncio.AbstractEventLoop) -> None:
    try:
        loop.create_task(coro)
    except RuntimeError:
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            fut.add_done_callback(self._on_bg_task_done)
        except Exception:
            _logger.debug("fire_and_forget failed", exc_info=True)
```

- **需要改成**：

1. `__init__` 中（第 48 行后）添加：
```python
self._pending_tasks: set[asyncio.Task] = set()
```

2. `_fire_and_forget` 改为：
```python
def _fire_and_forget(self, coro: Coroutine[Any, Any, Any], loop: asyncio.AbstractEventLoop) -> None:
    try:
        task = loop.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
    except RuntimeError:
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            fut.add_done_callback(self._on_bg_task_done)
        except Exception:
            coro.close()
            _logger.debug("fire_and_forget failed", exc_info=True)
```

- **冲突风险**：低。

---

### 修复 10：on_interrupted 异步路径 COMPLETING 重新检查（B3-01）

- **文件**：`controller/core.py`
- **修复逻辑**：`_wait_and_abort` 在 `await` flush 完成后直接设置 `ABORTED`，但 session 可能在等待期间已转为 `COMPLETING`。修复：await 后重新检查 `old_session.state == COMPLETING`，如果是则跳过 abort。
- **我们代码中对应的当前代码**（`controller/core.py` 第 434-451 行）：

```python
async def _wait_and_abort():
    try:
        await asyncio.wait_for(
            old_session.flush.wait_for_flush(),
            timeout=3.0,
        )
    except (asyncio.TimeoutError, Exception):
        _logger.debug(...)
    old_session.state = ABORTED
    old_session.flush.mark_completed()
    ...
```

- **需要改成**（在 `except` 块之后、`old_session.state = ABORTED` 之前插入）：

```python
    # v1.3.2 fix (B3-01): re-check COMPLETING after the await
    if old_session.state == COMPLETING:
        _logger.info(
            "on_interrupted: skip abort for msg=%s (session transitioned to COMPLETING during flush wait)",
            old_message_id[:12],
        )
        return
    old_session.state = ABORTED
```

- **冲突风险**：低。`COMPLETING` 已在 `controller/core.py` 第 24 行导入，可直接使用。

---

### 修复 11：_INTERRUPT_MAP_MAX 提升为模块级常量（P3-05）

- **文件**：`controller/core.py`
- **修复逻辑**：`_INTERRUPT_MAP_MAX = 200` 原本在 `on_interrupted` 方法内部每次调用重新定义。提升为模块级常量。
- **我们代码中对应的当前代码**：**我们的 fork 在 `on_interrupted` 末尾（第 499-502 行）没有 _interrupt_map 修剪逻辑。** 上游在分叉点已有此修剪，我们的 fork 没有。
- **需要改成**：

1. 在 `controller/core.py` 第 36 行后（`_logger` 之后）添加：
```python
_INTERRUPT_MAP_MAX = 200
```

2. 在 `on_interrupted` 第 502 行后添加修剪逻辑：
```python
        # Prevent unbounded growth: keep only the most recent entries
        if len(self._interrupt_map) > _INTERRUPT_MAP_MAX:
            excess = len(self._interrupt_map) - _INTERRUPT_MAP_MAX
            # Remove oldest entries (first inserted)
            for key in list(self._interrupt_map.keys())[:excess]:
                del self._interrupt_map[key]
```

- **冲突风险**：低。这是新增逻辑。

---

### 修复 12：/stop 响应检测改为三重条件（B3-04）

- **文件**：`patching/adapter.py`
- **修复逻辑**：原 `any(kw in content for kw in ("已停止", ...))` 会对含 "已停止" 的正常 AI 回答误触发。改为三重条件：长度 < 50 + 以 ⚡ 开头 + 包含关键词。
- **我们代码中对应的当前代码**（`patching/adapter.py` 第 157 行）：

```python
_is_stop_response = any(kw in content for kw in ("已停止", "stopped", "Stopped"))
```

- **需要改成**：

```python
_stripped = content.strip()
_is_stop_response = (
    len(_stripped) < 50
    and _stripped.startswith("⚡")
    and any(kw in _stripped for kw in ("已停止", "stopped", "Stopped"))
)
```

- **冲突风险**：低。

---

### 修复 13：_schedule_confirm_card 移除冗余 import asyncio（B3-05）

- **文件**：`patching/adapter.py`
- **修复逻辑**：`asyncio` 已在模块级导入，`_schedule_confirm_card` 内的 `import asyncio` 冗余。
- **我们代码中对应的当前代码**（`patching/adapter.py` 第 654 行）：

```python
    import asyncio
```

- **需要改成**：删除该行。
- **冲突风险**：无。

---

### 修复 14：_hls_bg_sending / _hls_cron_sending 计数器默认值统一（B3-06）

- **文件**：`patching/gateway.py`
- **修复逻辑**：上游将 `_hls_bg_sending` 从布尔改为计数器，但 `finally` 块中 `getattr(adapter, '_hls_bg_sending', 1) - 1` 默认值为 1（应为 0）。修复：默认值改为 0。
- **我们代码中对应的当前代码**：

我们的 fork **仍使用布尔值**（`True`/`False`），不是计数器：
- 第 775 行：`adapter._hls_bg_sending = True`
- 第 782 行：`adapter._hls_bg_sending = False`
- 第 958 行：`feishu_adapter._hls_cron_sending = True`
- 第 963 行：`feishu_adapter._hls_cron_sending = False`

- **需要改成**：此修复**不直接适用**。我们的 fork 用布尔值，而上游在 3fd7a08 中已改为计数器。需要先决定是否移植计数器方案。如果保持布尔值，则不需要此修复。如果要移植计数器方案（防止并发 background task 互相覆盖），需要完整移植 3fd7a08 中 `_wrap_run_background_task` 的计数器逻辑。
- **冲突风险**：高。涉及架构决策。

---

### 修复 15：_stream_consumed_len 清理防止内存泄漏（P3-02）

- **文件**：`patching/callbacks.py`
- **修复逻辑**：`_stream_consumed_len` 字典在消息完成后不清理，长时间运行时无限增长。修复：添加 `_cleanup_consumed_len` 函数，在 `already_streamed=True` 和 `length_dedup` 两个分支中调用。
- **我们代码中对应的当前代码**（`patching/callbacks.py` 第 152 行 + 第 246-251 行 + 第 255-261 行）：

第 152 行后需添加：
```python
def _cleanup_consumed_len(_eid: str) -> None:
    """Remove consumed-length tracking for a completed message."""
    _stream_consumed_len.pop(_eid, None)
```

第 251 行（`already_streamed` 分支的 `return _orig_interim` 之前）添加：
```python
                    _cleanup_consumed_len(_eid)
```

第 261 行（`length_dedup` 分支的 `return _orig_interim` 之前）添加：
```python
                    _cleanup_consumed_len(_eid)
```

- **冲突风险**：低。我们的 callbacks.py 结构与上游一致。

---

### 修复 16：aowen/__init__.py — get_event_loop → get_running_loop + Task 强引用

- **文件**：`aowen/__init__.py`
- **修复逻辑**：`asyncio.get_event_loop()` 在 Python 3.14 中会 raise RuntimeError。改为 `get_running_loop()`。同时持有 Task 强引用。
- **我们代码中对应的当前代码**（`aowen/__init__.py` 第 852-853 行）：

```python
    loop = asyncio.get_event_loop()
    loop.create_task(_send())
```

- **需要改成**：

1. 模块级（第 37 行 `_logger` 之后）添加：
```python
_aowen_pending_tasks: set = set()
```

2. 第 852-853 行改为：
```python
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _logger.warning("HLS: /aowen %s but no running event loop", cmd_name)
        return
    task = loop.create_task(_send())
    _aowen_pending_tasks.add(task)
    task.add_done_callback(_aowen_pending_tasks.discard)
```

- **冲突风险**：低。注意我们的 `_send_card_async` 内部协程名是 `_send()`（上游是 `_init_and_send()`）。

---

### 修复 17：plugin/__init__.py — get_event_loop → get_running_loop

- **文件**：`plugin/__init__.py`
- **修复逻辑**：同上，废弃 API 替换。
- **我们代码中对应的当前代码**（`plugin/__init__.py` 第 243-248 行）：

```python
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ctrl._ensure_init())
                _logger.info(...)
            else:
                _logger.debug("... event loop not running, skipping pre-warm", ...)
```

- **需要改成**：

```python
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                _logger.debug("... no running event loop, skipping pre-warm", ...)
                return
            if loop.is_running():
                loop.create_task(ctrl._ensure_init())
                _logger.info(...)
```

- **冲突风险**：低。

---

### 修复 18：controller/linear_mixin.py — get_event_loop → get_running_loop

- **文件**：`controller/linear_mixin.py`
- **修复逻辑**：同上。
- **我们代码中对应的当前代码**（`controller/linear_mixin.py` 第 292 行）：

```python
                    asyncio.get_event_loop().create_task(
```

- **需要改成**：

```python
                    asyncio.get_running_loop().create_task(
```

- **冲突风险**：无。单行替换。

---

### 修复 19：feishu/client.py — upload_image 增加 try/except（P1-03）

- **文件**：`feishu/client.py`
- **修复逻辑**：`upload_image` 的 API 调用部分（`acreate`）没有 try/except，网络错误或认证失败会未捕获传播。
- **我们代码中对应的当前代码**（`feishu/client.py` 第 745-754 行）：

```python
        file = io.BytesIO(data)
        request = (
            CreateImageRequest.builder()
            .request_body(CreateImageRequestBody.builder().image_type("message").image(file).build())
            .build()
        )
        resp = await self._client.im.v1.image.acreate(request)
        if resp.success() and resp.data and resp.data.image_key:
            return str(resp.data.image_key)
        return None
```

- **需要改成**：

```python
        try:
            file = io.BytesIO(data)
            request = (
                CreateImageRequest.builder()
                .request_body(CreateImageRequestBody.builder().image_type("message").image(file).build())
                .build()
            )
            resp = await self._client.im.v1.image.acreate(request)
            if resp.success() and resp.data and resp.data.image_key:
                return str(resp.data.image_key)
            return None
        except Exception:
            _logger.debug("image upload (API call) failed for %s", image_url, exc_info=True)
            return None
```

- **冲突风险**：低。

---

### 修复 20：7 处 except Exception: pass → debug 日志（P3-01）

- **文件**：`controller/core.py`、`controller/linear_mixin.py`、`feishu/client.py`
- **修复逻辑**：将 7 处 `except Exception: pass` 改为 `except Exception: _logger.debug('...', exc_info=True)`。
- **我们代码中对应位置**：

| 文件 | 行号 | 当前 |
|---|---|---|
| `controller/core.py` | 第 208 行 | `except Exception: pass`（record_card_created） |
| `controller/core.py` | 第 380-381 行 | `except Exception: pass`（record_card_aborted） |
| `controller/linear_mixin.py` | 第 1792-1793 行 | `except Exception: pass`（record_full_rebuild） |
| `controller/linear_mixin.py` | 第 1821-1822 行 | `except Exception: pass`（record_card_completed） |
| `controller/linear_mixin.py` | 第 1838-1839 行 | `except Exception: pass`（record_card_failed） |
| `feishu/client.py` | 第 262-263 行 | `except Exception: pass`（record_api_call） |
| `feishu/client.py` | 第 303-304 行 | `except Exception: pass`（record_api_error） |

- **需要改成**：每处 `pass` → `_logger.debug('metrics: record_XXX failed', exc_info=True)`
- **冲突风险**：无。纯机械替换。

---

### 修复 21：__init__.py docstring 修正

- **文件**：`__init__.py`
- **修复逻辑**：docstring 与代码矛盾：100ms → 200ms，TTL 延长 → 300309 fallback。
- **我们代码中对应的当前代码**（`__init__.py` 第 114-115 行）：

```python
  - Default flush interval 100ms (configurable 70~2000ms)
  - Proactive TTL extension prevents 300309 stream closure
```

- **需要改成**：

```python
  - Default flush interval 200ms (configurable 70~2000ms)
  - 300309 stream-closed fallback ensures content delivery on long conversations
```

- **冲突风险**：低。但如果我们的 fork 决定保持 100ms 默认值（见修复 5 的 `flush_interval_ms` 默认值差异），则只需改第二行。

---

## 补丁优先级排序

| 优先级 | 修复编号 | 描述 | 文件 |
|---|---|---|---|
| P0 | 3 | FeishuAdapter import 路径 | `patching/hermes_adapter.py` — **已修复** |
| P0 | 4 | 参数名对齐 | `patching/gateway.py` |
| P0 | 2 | EphemeralReply 直通 | `patching/adapter.py` |
| P1 | 1 | _gateway_cards 内存泄漏 | `patching/adapter.py` |
| P1 | 6 | _send_text_fallback 时序 | `controller/core.py` |
| P1 | 5+7 | _to_int/_to_float + nan/inf | `config/reader.py` |
| P1 | 8 | OSError/UnicodeDecodeError | `config/reader.py` |
| P1 | 9 | _fire_and_forget Task 强引用 | `controller/core.py` |
| P1 | 10 | COMPLETING 重新检查 | `controller/core.py` |
| P1 | 19 | upload_image try/except | `feishu/client.py` |
| P2 | 12 | /stop 三重检测 | `patching/adapter.py` |
| P2 | 11 | _INTERRUPT_MAP_MAX 模块级 | `controller/core.py` |
| P2 | 16 | aowen get_running_loop | `aowen/__init__.py` |
| P2 | 17 | plugin get_running_loop | `plugin/__init__.py` |
| P2 | 18 | linear_mixin get_running_loop | `controller/linear_mixin.py` |
| P3 | 15 | _stream_consumed_len 清理 | `patching/callbacks.py` |
| P3 | 13 | 移除冗余 import asyncio | `patching/adapter.py` |
| P3 | 14 | _hls_bg_sending 默认值 | `patching/gateway.py` — **需架构决策** |
| P3 | 20 | except: pass → debug 日志 | 多文件 |
| P3 | 21 | docstring 修正 | `__init__.py` |
