# 上游 P0/P1 修复补丁分析 — 应用到 fork 的精确说明

> 生成时间：2026-06-30
> 分析基于：upstream/github_sync 的 3 个 commit (a209e72, 5ef0dbd, 0df7d85)
> 目标分支：sync/upstream-p0-p1（基于 main, fork at 0ae8d70）
> 文件路径相对于插件根目录 `/home/core/.hermes/plugins/hermes-lark-streaming/`

---

## 目录

- [Commit 1: a209e72 — P0-05 占位卡永久卡住 Phase2 失败死锁](#commit-1)
- [Commit 2: 5ef0dbd — P0-06 concurrency seal 重复 session + P1 多项修复](#commit-2)
- [Commit 3: 0df7d85 — P0-07 deferred loading 补丁打在替身类（v1.4.0 最关键修复）](#commit-3)
- [冲突风险总结](#conflict-summary)

---

## Commit 1: a209e72 — P0-05 占位卡永久卡住 Phase2 失败死锁 {#commit-1}

### 根因
Phase 2 `batch_update` 失败后 `_creation_stages` 为空，所有写入路径（drain/seal）检查 `_creation_stages` 跳过写入，seal 静默成功不写内容，全量重建 fallback 永不触发，卡片永久卡在占位状态"正在加载上下文..."。

### 修复 1.1: Phase 2 transient error 重置 `_first_flush_done`

| 项目 | 内容 |
|---|---|
| **文件** | `controller/linear_mixin.py` |
| **行号** | 631-633 |
| **冲突风险** | 低 |

**当前代码**（行 631-633）:
```python
                    else:
                        _logger.warning("unified flush phase 2 batch_update failed: %s", e)
                        return
```

**改为**:
```python
                    else:
                        # v1.3.3 fix (P0): transient API error (rate limit, auth
                        # refresh, etc.) — _creation_stages stays empty. Reset
                        # _first_flush_done so next content retries via flush_now.
                        _logger.warning(
                            "unified flush phase 2 batch_update failed: %s — "
                            "resetting _first_flush_done for retry, card=%s",
                            e, session.card_id[:12] if session.card_id else "?",
                        )
                        session._first_flush_done = False
                        return
```

### 修复 1.2: Phase 2 外层 `except Exception` 捕获非 FeishuAPIError

| 项目 | 内容 |
|---|---|
| **文件** | `controller/linear_mixin.py` |
| **行号** | 在修复 1.1 的 `return` 之后（行 633 后），行 635 `# ── Stream answer text if also dirty ──` 之前插入 |
| **冲突风险** | 低 |

**当前代码**: 无此 except 块（Phase 2 try 只有 `except FeishuAPIError`）

**新增**（在 `return` 之后、`# ── Stream answer text` 之前插入）:
```python
                except Exception as e:
                    # v1.3.3 fix (P0): catch non-FeishuAPIError exceptions (network
                    # timeout, connection error, etc.) that would otherwise propagate
                    # to FlushController._do_flush's except Exception, leaving
                    # _creation_stages empty and causing the "placeholder card stuck
                    # forever" bug.
                    # Reset _first_flush_done so the next content arrival retries
                    # Phase 2 via immediate flush_now instead of throttled schedule.
                    _logger.warning(
                        "unified flush phase 2 non-API exception: %s — "
                        "resetting _first_flush_done for retry, card=%s",
                        e, session.card_id[:12] if session.card_id else "?",
                        exc_info=True,
                    )
                    session._first_flush_done = False
                    return
```

### 修复 1.3: `_do_linear_complete` 检测 Phase 2 从未成功 → 强制全量重建

| 项目 | 内容 |
|---|---|
| **文件** | `controller/linear_mixin.py` |
| **行号** | 1668-1693（footer_data 构建到 preservative seal 分支） |
| **冲突风险** | 低-中（我们 fork 的 footer_data 可能不同，但 seal 分支结构一致） |

**当前代码**（行 1668-1693）:
```python
        # ── Build footer data ──
        footer_data = session.footer
        is_error = session.state in (CREATION_FAILED, TERMINATED)
        is_aborted = getattr(session, "_was_aborted", False) or session.state == ABORTED
        error_message = getattr(session, "error_message", "")

        # ── Step 5: Try preservative seal ──
        # v1.1.3: IM 降级模式用 update_card 封卡（不走 _preservative_seal）
        if not session.use_cardkit and session.card_msg_id:
            seal_ok = await self._do_im_fallback_seal(
                session,
                footer_data=footer_data,
                is_error=is_error,
                is_aborted=is_aborted,
                error_message=error_message,
            )
        else:
            seal_ok = await self._preservative_seal(
                session,
                footer_data=footer_data,
                is_error=is_error,
                is_aborted=is_aborted,
                error_message=error_message,
                footer_fields=self._cfg.footer_fields,
                footer_show_label=self._cfg.footer_show_label,
            )
```

**改为**（在 `# ── Build footer data ──` 之前插入检测逻辑，并修改 seal 分支添加 `elif`）:
```python
        # v1.3.3 fix (P0 — issue: placeholder_card_stuck):
        # Detect if Phase 2 never succeeded (answer element was never created).
        # If so, the preservative seal's content guards will ALL skip (they
        # check "answer"/"panel" in _creation_stages), and the seal would
        # "succeed" at closing streaming mode without writing ANY content —
        # leaving the card permanently stuck at "正在加载上下文...".
        # Force seal_ok=False to trigger the full card rebuild fallback,
        # which replaces the entire card with complete content via
        # build_unified_complete_card + cardkit_update.
        _phase2_never_succeeded = (
            session.use_cardkit  # Only CardKit path has Phase 2
            and session.card_id  # Card was created
            and "answer" not in session._creation_stages  # Phase 2 never succeeded
            and state is not None
            and (state.answer_text or state.panel_visible or state.reasoning_rounds)
        )
        if _phase2_never_succeeded:
            _logger.warning(
                "HLS: Phase 2 never succeeded (no answer element created) — "
                "card stuck at placeholder, forcing full rebuild: card=%s trace=%s "
                "answer_len=%d panel_visible=%s",
                (session.card_id or "")[:12], session.card_trace_id,
                len(state.answer_text) if state else 0,
                state.panel_visible if state else False,
            )

        # ── Build footer data ──
        footer_data = session.footer
        is_error = session.state in (CREATION_FAILED, TERMINATED)
        is_aborted = getattr(session, "_was_aborted", False) or session.state == ABORTED
        error_message = getattr(session, "error_message", "")

        # ── Step 5: Try preservative seal ──
        # v1.1.3: IM 降级模式用 update_card 封卡（不走 _preservative_seal）
        if not session.use_cardkit and session.card_msg_id:
            seal_ok = await self._do_im_fallback_seal(
                session,
                footer_data=footer_data,
                is_error=is_error,
                is_aborted=is_aborted,
                error_message=error_message,
            )
        elif _phase2_never_succeeded:
            # v1.3.3 fix (P0): Phase 2 never succeeded — skip preservative
            # seal (which would silently succeed without writing content)
            # and force full rebuild to replace the entire placeholder card.
            seal_ok = False  # 触发下方全量重建 fallback
        else:
            seal_ok = await self._preservative_seal(
                session,
                footer_data=footer_data,
                is_error=is_error,
                is_aborted=is_aborted,
                error_message=error_message,
                footer_fields=self._cfg.footer_fields,
                footer_show_label=self._cfg.footer_show_label,
            )
```

---

## Commit 2: 5ef0dbd — P0-06 concurrency seal 重复 session + P1 多项修复 {#commit-2}

### 修复 2.1: concurrency seal 创建重复 session（P0）

| 项目 | 内容 |
|---|---|
| **文件** | `controller/core.py` |
| **行号** | 185（`loop = self._get_loop()` 之前插入） |
| **冲突风险** | 低 |

> **重要差异**: 上游用 `self._sess_get(message_id)` 和 `self._sess_active_count()`，但我们 fork **没有**这些封装方法（直接用 `self._sessions`）。需用 `self._sessions.get(message_id)` 和 `sum(1 for s in self._sessions.values() if not s.is_terminal_phase)` 替代。

**当前代码**（行 185-189）:
```python
        loop = self._get_loop()
        if loop is None:
            _logger.warning("HLS: no event loop, skipping msg=%s", (message_id or "?")[:12])
            return
        session = CardSession(
```

**改为**（在 `loop = self._get_loop()` 之前插入）:
```python
        # v1.3.4 fix (P0): concurrency seal 可能已通过 on_interrupted 创建了
        # 当前 message_id 的 session（并已触发 _do_create_linear_card）。
        # 如果直接再创建会覆盖原 session，导致：
        #   1. 两张卡片被创建（on_interrupted 一张 + 这里一张）
        #   2. on_interrupted 创建的那张卡片成为孤儿（永远停在"正在加载上下文..."）
        # 修复：如果 session 已存在（由 on_interrupted 创建），直接复用，仅补记 metrics。
        existing = self._sessions.get(message_id)
        if existing is not None:
            _logger.info(
                "HLS: session already created by concurrency seal, reusing msg=%s trace=%s",
                (message_id or "?")[:12], existing.card_trace_id,
            )
            try:
                from ..aowen import record_card_created, set_active_sessions
                record_card_created()
                set_active_sessions(sum(1 for s in self._sessions.values() if not s.is_terminal_phase))
            except Exception:
                _logger.debug('metrics: record_card_created failed (reuse path)', exc_info=True)
            return

        loop = self._get_loop()
```

### 修复 2.2: Phase 2 schema_error → `_phase2_failed` 标志（P1）

| 项目 | 内容 |
|---|---|
| **文件** | `controller/linear_mixin.py` + `state/session.py` |
| **冲突风险** | 低 |

#### 2.2a: `state/session.py` — 新增 `_phase2_failed` slot + 初始化

**`__slots__`**（行 41-79）: 在 `"_first_flush_done"`（行 46）之后添加:
```python
        "_first_flush_done",
        "_phase2_failed",   # v1.3.4: Phase 2 永久失败标志
```

**`__init__`**（行 141 之后）:
```python
        self._first_flush_done: bool = False
        # v1.3.4: Phase 2 永久失败标志（schema_error / element_not_found）
        # 设置后跳过所有 Phase 2/3 flush，完成时走全量重建
        self._phase2_failed: bool = False
```

#### 2.2b: `controller/linear_mixin.py` — 函数顶部新增 `_phase2_failed` 守卫

**行号**: 505（`assert self._client is not None` 之后）

**当前代码**（行 505）:
```python
        assert self._client is not None
```

**改为**（在 `assert` 之后插入）:
```python
        assert self._client is not None

        # v1.3.4 fix (P1): Phase 2 永久失败（schema_error / element_not_found）
        # 时，不再重试 Phase 2 也不再执行 Phase 3（元素不存在，partial_update
        # 会无限返回 300313）。清空脏标志避免节流 flush 空转，等内容完成后
        # 由 _phase2_never_succeeded 检测并走全量重建。
        if getattr(session, "_phase2_failed", False):
            state.panel_dirty = False
            state.answer_dirty = False
            state.tool_steps_dirty = False
            return
```

#### 2.2c: `controller/linear_mixin.py` — schema_error 分支改为设置 `_phase2_failed`

**行号**: 613-630

> **注意**: 我们 fork 没有 `is_element_not_found_error` 的 Phase 2 分支（上游有，我们没有）。只有 `is_schema_error` 分支需要修改。

**当前代码**（行 613-630）:
```python
                    if is_schema_error(e):
                        # ── Schema error (300315): permanent, don't retry ──
                        # This typically means an invalid property on a CardKit
                        # element.  Log with full error so the developer can
                        # identify the offending property, then mark element as
                        # created to prevent infinite retry loops.
                        _logger.error(
                            "unified flush phase 2 SCHEMA ERROR (permanent): %s — "
                            "detail: %s — "
                            "marking elements as created to prevent retry loop, card=%s",
                            e, e.extract_schema_detail(), session.card_id[:12],
                        )
                        session._creation_stages.add("answer")  # Prevent retry loop
                        session._creation_stages.add("panel")
                        session._creation_stages.add("hint_removed")
                        # Fall through to Phase 3 (partial_update may still fail
                        # if panel wasn't actually added, but at least we won't
                        # loop infinitely on Phase 2)
```

**改为**:
```python
                    if is_schema_error(e):
                        # ── Schema error (300315): permanent, don't retry ──
                        # v1.3.4 fix (P1): 原实现 mark "answer" as created 会导致：
                        #   1. Phase 3 在不存在的元素上 partial_update → 300313 无限重试
                        #      （~15 次/秒 futile API calls，可能触发飞书频控）
                        #   2. _phase2_never_succeeded 守卫被掩盖（"answer" in stages → False）
                        #      → 完成时不走全量重建，改走 preservative seal（再次失败 2 次）
                        # 修复：设置 _phase2_failed 标志，清空脏数据，return。
                        _logger.error(
                            "unified flush phase 2 SCHEMA ERROR (permanent): %s — "
                            "detail: %s — "
                            "setting _phase2_failed, will full-rebuild at completion, card=%s",
                            e, e.extract_schema_detail(), session.card_id[:12],
                        )
                        session._phase2_failed = True
                        state.panel_dirty = False
                        state.answer_dirty = False
                        state.tool_steps_dirty = False
                        return
```

#### 2.2d: 更新 `_phase2_never_succeeded` 检测（与 Commit 1 的修复 1.3 合并）

在 Commit 1 的修复 1.3 中，`_phase2_never_succeeded` 只检查 `"answer" not in session._creation_stages`。Commit 2 增加了 `_phase2_failed` 条件：

**修改 Commit 1 中的 `_phase2_never_succeeded`**（在 `controller/linear_mixin.py`）:

```python
        _phase2_never_succeeded = (
            session.use_cardkit
            and session.card_id
            and (
                "answer" not in session._creation_stages  # Phase 2 never succeeded
                or getattr(session, "_phase2_failed", False)  # v1.3.4: Phase 2 permanently failed
            )
            and state is not None
            and (state.answer_text or state.panel_visible or state.reasoning_rounds)
        )
```

### 修复 2.3: `except asyncio.CancelledError` handler（P1）

| 项目 | 内容 |
|---|---|
| **文件** | `controller/linear_mixin.py` |
| **行号**: 在修复 1.2 的 `except Exception` 之前插入（Phase 2 try 块内） |
| **冲突风险** | 低 |

**修复逻辑**: Python 3.8+ 的 `CancelledError` 是 `BaseException` 子类，`except Exception` 无法捕获。需单独 `except asyncio.CancelledError`。

> **前提**: 需要先确认文件顶部已 `import asyncio`（我们 fork 的 `linear_mixin.py` 应该已有）。

**新增**（在修复 1.2 的 `except Exception as e:` 之前插入）:
```python
                except asyncio.CancelledError:
                    # v1.3.4 fix (P1): CancelledError 是 BaseException 子类，
                    # except Exception 无法捕获。如果 flush 任务被取消（gateway
                    # 关闭/超时），必须重置 _first_flush_done 否则下次内容到达走
                    # 节流而非立即 flush，增加"占位卡卡住"风险。重置后 re-raise。
                    _logger.debug(
                        "unified flush phase 2 cancelled — resetting _first_flush_done, card=%s",
                        session.card_id[:12] if session.card_id else "?",
                    )
                    session._first_flush_done = False
                    raise
```

### 修复 2.4: 网络错误重试 + 99991400 频控码（P1）

| 项目 | 内容 |
|---|---|
| **文件** | `feishu/client.py` |
| **冲突风险** | 低 |

#### 2.4a: 新增 httpx/ObtainAccessTokenException 导入

**行号**: 42（`ReplyMessageRequestBody,` 之后）

**当前代码**（行 42-44）:
```python
    ReplyMessageRequestBody,
)

_logger = logging.getLogger("hermes_lark_streaming")
```

**改为**:
```python
    ReplyMessageRequestBody,
)

# v1.3.4 fix (P1): lark_oapi SDK 的 Transport.aexecute 不捕获网络异常，
# httpx 的 ConnectError/ReadTimeout 等会裸传播；token 刷新失败抛
# ObtainAccessTokenException（Exception 子类，非 FeishuAPIError）。
# _retry_transient 的 except FeishuAPIError 无法捕获这些异常，导致
# 网络瞬断时 cardkit_create 直接失败走 IM 降级（用户看到纯文本而非卡片）。
# 导入这些异常类型用于 _retry_transient 的网络错误重试。
try:
    import httpx
    _NETWORK_ERROR_BASES: tuple = (httpx.RequestError, httpx.TimeoutException)
except ImportError:
    _NETWORK_ERROR_BASES = ()
try:
    from lark_oapi.core.exception import ObtainAccessTokenException
    _TOKEN_ERROR_BASES: tuple = (ObtainAccessTokenException,)
except ImportError:
    _TOKEN_ERROR_BASES = ()

_logger = logging.getLogger("hermes_lark_streaming")
```

#### 2.4b: 新增 99991400 到 CARDKIT_TRANSIENT_CODES

**行号**: 135-139

**当前代码**（行 135-139）:
```python
CARDKIT_TRANSIENT_CODES = {
    2200,   # CardKit 内部超时
    1663,   # CardKit 服务端瞬态错误
    300000, # CardKit 通用内部错误
}
```

**改为**:
```python
CARDKIT_TRANSIENT_CODES = {
    2200,     # CardKit 内部超时
    1663,     # CardKit 服务端瞬态错误
    300000,   # CardKit 通用内部错误
    99991400, # 接口频率限制（per-API rate limit，HTTP 400）
}
```

#### 2.4c: `_retry_transient` 新增网络错误/token 错误重试

**行号**: 265-277（`except FeishuAPIError` 块之后、`raise last_error` 之前）

**当前代码**（行 265-278）:
```python
            except FeishuAPIError as e:
                last_error = e
                if not _is_transient_error(e):
                    raise
                if attempt < max_retries:
                    delay = _TRANSIENT_RETRY_DELAYS[attempt]
                    _logger.info(
                        "transient retry: %s attempt=%d/%d code=%s delay=%.2fs",
                        operation, attempt + 1, max_retries, e.code, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise last_error  # unreachable, but type-safe
```

**改为**:
```python
            except FeishuAPIError as e:
                last_error = e
                if not _is_transient_error(e):
                    raise
                if attempt < max_retries:
                    delay = _TRANSIENT_RETRY_DELAYS[attempt]
                    _logger.info(
                        "transient retry: %s attempt=%d/%d code=%s delay=%.2fs",
                        operation, attempt + 1, max_retries, e.code, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except asyncio.CancelledError:
                # v1.3.4: 不要吞 CancelledError，让它正常传播
                raise
            except _NETWORK_ERROR_BASES as e:
                # v1.3.4 fix (P1): 网络错误（httpx ConnectError/ReadTimeout 等）
                # 是瞬态的，重试后通常成功。
                if attempt < max_retries:
                    delay = _TRANSIENT_RETRY_DELAYS[attempt]
                    _logger.info(
                        "transient retry (network): %s attempt=%d/%d error=%s delay=%.2fs",
                        operation, attempt + 1, max_retries, type(e).__name__, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except _TOKEN_ERROR_BASES as e:
                # v1.3.4 fix (P1): token 刷新失败可能因网络瞬断，重试通常成功。
                if attempt < max_retries:
                    delay = _TRANSIENT_RETRY_DELAYS[attempt]
                    _logger.info(
                        "transient retry (token): %s attempt=%d/%d error=%s delay=%.2fs",
                        operation, attempt + 1, max_retries, type(e).__name__, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise last_error  # unreachable, but type-safe
```

> ⚠️ **注意**: 当 `_NETWORK_ERROR_BASES` 为空 tuple `()` 时，`except ()` 不会匹配任何异常，所以即使 httpx 不可用也是安全的。

### 修复 2.5: `_msg_ctx` 泄漏修复（P1）— gateway.py 三处 wrapper

| 项目 | 内容 |
|---|---|
| **文件** | `patching/gateway.py` |
| **冲突风险** | 中（我们 fork 可能改过 gateway.py 的 wrapper 结构） |

#### 2.5a: `_wrap_handle_message_with_agent` — cleanup helper

**行号**: 149-151（`result = await orig(...)`）+ 170-171, 190, 286-301

**修复逻辑**: 抽取 `_hls_cleanup_ctx()` helper，在 `orig()` 抛异常时也执行 cleanup。三处 `_started_msg_ids.discard(mid)` + 末尾 cleanup 统一调用 helper。

**当前代码**（行 149-151）:
```python
        _msg_ctx.set(msg_context)

        result = await orig(self, event, source, *args, **kwargs)
```

**改为**:
```python
        _msg_ctx.set(msg_context)

        # v1.3.4 fix (P1): 确保 orig() 抛异常时 _msg_ctx / _started_msg_ids 被清理
        def _hls_cleanup_ctx() -> None:
            with _started_msg_ids_lock:
                _started_msg_ids.discard(mid)
            _msg_ctx.set(None)
            _thread_local_ctx.data = None

        try:
            result = await orig(self, event, source, *args, **kwargs)
        except BaseException:
            _hls_cleanup_ctx()
            raise
```

**然后替换三处内联 cleanup**:

1. 行 170-171:
```python
                with _started_msg_ids_lock:
                    _started_msg_ids.discard(mid)
```
→
```python
                _hls_cleanup_ctx()
```

2. 行 190（`_started_msg_ids.discard(mid)` 那处）:
```python
                                _started_msg_ids.discard(mid)
```
→
```python
                                _hls_cleanup_ctx()
```

3. 行 286-301（函数末尾 cleanup）:
```python
        # Cleanup tracking
        with _started_msg_ids_lock:
            _started_msg_ids.discard(mid)

        # ── Clear message context to prevent stale leakage ──
        # ... (长注释)
        _msg_ctx.set(None)
        _thread_local_ctx.data = None

        return result
```
→
```python
        # v1.3.4 fix (P1): cleanup on normal exit path (early returns and
        # exceptions handled by _hls_cleanup_ctx above).
        _hls_cleanup_ctx()

        return result
```

#### 2.5b: `_wrap_run_agent` — try/except BaseException 恢复 parent ctx

**行号**: 行 390 附近（`result = await orig(...)` 调用处）+ 行 650-652（restore parent ctx）

**当前代码**（`_wrap_run_agent` 中 `orig()` 调用 + 末尾 restore）:

需找到 `result = await orig(self, message, context_prompt, ...)` 那行，用 try/except BaseException 包裹。

**改为**:
```python
        # v1.3.4 fix (P1): 确保 orig() 抛异常时 _saved_parent_ctx 被恢复。
        try:
            result = await orig(
                self,
                message,
                context_prompt,
                history,
                source,
                session_id,
                session_key=session_key,
                run_generation=run_generation,
                _interrupt_depth=_interrupt_depth,
                event_message_id=event_message_id,
                channel_prompt=channel_prompt,
                **kwargs,
            )
        except BaseException:
            if _saved_parent_ctx is not None:
                _msg_ctx.set(_saved_parent_ctx)
                _thread_local_ctx.data = dict(_saved_parent_ctx)
            raise
```

#### 2.5c: `_wrap_run_background_task` — orig + COMPLETE 都在 try 内，finally cleanup

**行号**: 777-837

**当前代码结构**:
```python
        try:
            result = await orig(self, prompt, source, task_id, **kwargs)
        finally:
            if original_send and adapter:
                adapter.send = original_send
                adapter._hls_bg_sending = False  # 或 getattr 降级

        # ── Fire COMPLETE hook ──
        ctx = _msg_ctx.get()
        if ctx is not None:
            # ... COMPLETE hook 逻辑 ...

        # Clear context
        _msg_ctx.set(None)
        _thread_local_ctx.data = None

        return result
```

**改为**（将 COMPLETE hook 移入 try 块，在 finally 中同时恢复 adapter.send 和清理 _msg_ctx）:
```python
        # v1.3.4 fix (P1): orig() + COMPLETE hook 都在 try 块内，finally
        # 同时恢复 adapter.send 和清理 _msg_ctx。
        try:
            result = await orig(self, prompt, source, task_id, **kwargs)

            # ── Fire COMPLETE hook ──
            ctx = _msg_ctx.get()
            if ctx is not None:
                try:
                    from .hooks import on_message_completed

                    _elapsed = time.monotonic() - ctx.get("_msg_start_time", time.monotonic())

                    _agent_ref = ctx.get("_agent_ref")
                    cache_read = getattr(_agent_ref, "session_cache_read_tokens", 0) if _agent_ref else 0
                    cache_write = getattr(_agent_ref, "session_cache_write_tokens", 0) if _agent_ref else 0
                    reasoning_tokens = getattr(_agent_ref, "session_reasoning_tokens", 0) if _agent_ref else 0
                    estimated_cost_usd = getattr(_agent_ref, "session_estimated_cost_usd", 0) if _agent_ref else 0
                    cost_status = getattr(_agent_ref, "session_cost_status", "unknown") if _agent_ref else "unknown"

                    card_sent = on_message_completed(
                        message_id=task_id,
                        answer=(result or {}).get("final_response", ""),
                        duration=_elapsed,
                        model=(result or {}).get("model", ""),
                        tokens={
                            "input_tokens": (result or {}).get("input_tokens", 0),
                            "output_tokens": (result or {}).get("output_tokens", 0),
                            "cache_read_tokens": cache_read,
                            "cache_write_tokens": cache_write,
                        },
                        context={
                            "used_tokens": (result or {}).get("last_prompt_tokens", 0),
                            "max_tokens": (result or {}).get("context_length", 0),
                        },
                        api_calls=(result or {}).get("api_calls", 0),
                        history_offset=(result or {}).get("history_offset", 0),
                        compression_exhausted=(result or {}).get("compression_exhausted", False),
                        aborted=False,
                        error_message=(result or {}).get("error") or "",
                        reasoning_tokens=reasoning_tokens,
                        estimated_cost_usd=estimated_cost_usd,
                        cost_status=cost_status,
                    )

                    if card_sent:
                        ctx["card_sent"] = True
                        if result is not None and isinstance(result, dict):
                            result["_hls_card_sent"] = True
                except Exception:
                    _logger.debug("background task COMPLETE hook failed", exc_info=True)

            return result
        finally:
            if original_send and adapter:
                adapter.send = original_send
                adapter._hls_bg_sending = getattr(adapter, '_hls_bg_sending', 0) - 1
            # v1.3.4 fix (P1): clear context in finally — runs on ALL paths
            _msg_ctx.set(None)
            _thread_local_ctx.data = None
```

> ⚠️ **注意**: 我们 fork 的 `_hls_bg_sending` 减值方式可能与上游不同（上游用 `getattr(adapter, '_hls_bg_sending', 0) - 1`，我们 fork 可能直接 `= False`）。需确认我们 fork 中此处的实际代码再修改。

### 修复 2.6: `inspect.signature` 防御（P1）

| 项目 | 内容 |
|---|---|
| **文件** | `patching/gateway.py`（行 690）+ `patching/__init__.py`（行 613） |
| **冲突风险** | 低 |

#### 2.6a: `patching/gateway.py` 行 690

**当前代码**:
```python
        orig_params = inspect.signature(orig).parameters
```

**改为**:
```python
        # v1.3.4 fix (P1): inspect.signature 可能对 C 扩展/wrapped callable 抛异常
        try:
            orig_params = inspect.signature(orig).parameters
        except (ValueError, TypeError):
            orig_params = {}
```

#### 2.6b: `patching/__init__.py` 行 613

**当前代码**:
```python
            orig_params = inspect.signature(_orig_method).parameters
```

**改为**:
```python
            # v1.3.4 fix (P1): inspect.signature 可能对 C 扩展/wrapped callable 抛异常
            try:
                orig_params = inspect.signature(_orig_method).parameters
            except (ValueError, TypeError):
                orig_params = {}
```

### 修复 2.7: ABORTED→COMPLETED 非法状态转换（P1）

| 项目 | 内容 |
|---|---|
| **文件** | `controller/linear_mixin.py` |
| **行号** | 1802-1803 |
| **冲突风险** | 低 |

**当前代码**（行 1802-1803）:
```python
        if seal_ok:
            session.state = COMPLETED
```

**改为**:
```python
        if seal_ok:
            # v1.3.4 fix (P1): 如果会话已被 on_aborted 标记为 ABORTED，
            # 不要覆盖为 COMPLETED——否则状态机不一致（ABORTED→COMPLETED 非法转换）。
            if session._was_aborted:
                session.state = ABORTED
            else:
                session.state = COMPLETED
```

### 修复 2.8: bg_review_messages 注入 footer_data（P2）

| 项目 | 内容 |
|---|---|
| **文件** | `controller/linear_mixin.py` |
| **行号** | 1669（`footer_data = session.footer` 之后） |
| **冲突风险** | 低 |

**当前代码**（行 1669）:
```python
        footer_data = session.footer
```

**改为**:
```python
        footer_data = session.footer
        # v1.3.4 fix (P2): bg_review_messages 存在 state 中但从未传给
        # build_unified_complete_card，导致后台审查消息被静默丢弃。
        if state and state.bg_review_messages:
            if footer_data is None:
                footer_data = {}
            footer_data = {**footer_data, "bg_review_messages": list(state.bg_review_messages)}
```

> **前提**: 需确认 `UnifiedLinearState` 有 `bg_review_messages` 属性。

### 修复 2.9: FlushController Task 强引用防 GC（P2）

| 项目 | 内容 |
|---|---|
| **文件** | `flush/controller.py` |
| **冲突风险** | 低 |

#### 2.9a: `__init__` 新增 `_pending_flush_tasks`

**行号**: 45（`self._flush_resolvers` 之后）

**当前代码**（行 45 附近）:
```python
        self._flush_resolvers: list[asyncio.Future[None]] = []
```

**改为**:
```python
        self._flush_resolvers: list[asyncio.Future[None]] = []
        # v1.3.4 fix (P2): 持有 flush Task 强引用，防止 GC 在任务完成前回收
        self._pending_flush_tasks: set[asyncio.Task[None]] = set()
```

#### 2.9b: `_do_flush_task` 改用 `_create_flush_task`

**行号**: 166-168

**当前代码**:
```python
    def _do_flush_task(self, do_flush: Callable[[], Awaitable[None]]) -> None:
        self._pending_timer = None
        self._get_loop().call_soon(asyncio.create_task, self._do_flush(do_flush))
```

**改为**:
```python
    def _do_flush_task(self, do_flush: Callable[[], Awaitable[None]]) -> None:
        self._pending_timer = None
        # v1.3.4 fix (P2): 持有 Task 强引用防止 GC 回收
        self._get_loop().call_soon(self._create_flush_task, do_flush)

    def _create_flush_task(self, do_flush: Callable[[], Awaitable[None]]) -> None:
        task = self._get_loop().create_task(self._do_flush(do_flush))
        self._pending_flush_tasks.add(task)
        task.add_done_callback(self._pending_flush_tasks.discard)
```

#### 2.9c: `_do_flush` reflush 也用 `_create_flush_task`

**行号**: 194

**当前代码**:
```python
            self._get_loop().call_soon(asyncio.create_task, self._do_flush(do_flush))
```

**改为**:
```python
            # v1.3.4 fix (P2): 持有 Task 强引用防止 GC 回收
            self._get_loop().call_soon(self._create_flush_task, do_flush)
```

### 修复 2.10: /aowen handler 异常返回 `_skip`（P0）

| 项目 | 内容 |
|---|---|
| **文件** | `aowen/__init__.py` |
| **行号** | 804-806 |
| **冲突风险** | 低 |

**当前代码**（行 804-806）:
```python
    except Exception:
        _logger.debug("HLS: /aowen handler error", exc_info=True)
        return None
```

**改为**:
```python
    except Exception:
        # v1.3.4 fix (P0): /aowen 已识别但 handler 抛异常时，必须返回 skip
        # 阻止消息进入 agent。否则 /aowen foo 会被 LLM 当作用户 prompt 处理。
        _logger.exception("HLS: /aowen handler error — suppressing agent dispatch")
        return _skip("/aowen handler error suppressed")
```

### 修复 2.11: 错误面板 i18n_content（P1）

| 项目 | 内容 |
|---|---|
| **文件** | `cardkit/elements.py` |
| **行号** | 850-886（`_build_error_panel` 函数） |
| **冲突风险** | 中（我们 fork 可能已改过 error panel） |

> **注意**: 我们 fork 的 `_build_error_panel` 用了 `<details>` HTML 标签而非上游的 `---\n**技术详情**\n```...``` ` markdown 格式。需要保留我们的格式但添加 i18n_content。

**当前代码**（行 850-886）:
```python
    if is_aborted:
        en_label, zh_label = _T["interrupt_panel"]
        border_color = "orange"
        body_content = error_message
    else:
        en_label, zh_label = _T["error_panel"]
        border_color = "red"
        friendly_en = "AI encountered an error while replying. Please try again."
        friendly_zh = "AI 回复时出现错误，请重试。"
        if card_trace_id:
            friendly_en += f"\n\nDebug ID: `{card_trace_id}`"
            friendly_zh += f"\n\n调试 ID: `{card_trace_id}`"
        tech_detail = error_message.strip() if error_message else ""
        if tech_detail:
            body_content = f"{friendly_zh}\n\n<details><summary>技术详情</summary>\n\n```\n{tech_detail}\n```\n\n</details>"
        else:
            body_content = friendly_zh

    panel = _collapsible_panel(
        ...
        elements=[{
            "tag": "markdown",
            "content": body_content,
            "text_size": "notation",
        }],
        ...
    )
```

**改为**（保留我们 fork 的 `<details>` 格式，但增加 `body_i18n` 和 `markdown_el`）:
```python
    if is_aborted:
        en_label, zh_label = _T["interrupt_panel"]
        border_color = "orange"
        body_content = error_message
        body_i18n = None  # 中断消息无需 i18n
    else:
        en_label, zh_label = _T["error_panel"]
        border_color = "red"
        friendly_en = "AI encountered an error while replying. Please try again."
        friendly_zh = "AI 回复时出现错误，请重试。"
        if card_trace_id:
            friendly_en += f"\n\nDebug ID: `{card_trace_id}`"
            friendly_zh += f"\n\n调试 ID: `{card_trace_id}`"
        tech_detail = error_message.strip() if error_message else ""
        if tech_detail:
            body_content = f"{friendly_zh}\n\n<details><summary>技术详情</summary>\n\n```\n{tech_detail}\n```\n\n</details>"
            body_content_en = f"{friendly_en}\n\n<details><summary>Technical Details</summary>\n\n```\n{tech_detail}\n```\n\n</details>"
            body_i18n = _i18n(body_content_en, body_content)
        else:
            body_content = friendly_zh
            body_i18n = _i18n(friendly_en, friendly_zh)

    # v1.3.4 fix (P1): markdown 元素添加 i18n_content，英文 locale 用户看到英文
    markdown_el: dict[str, Any] = {
        "tag": "markdown",
        "content": body_content,
        "text_size": "notation",
    }
    if body_i18n is not None:
        markdown_el["i18n_content"] = body_i18n

    panel = _collapsible_panel(
        ...
        elements=[markdown_el],
        ...
    )
```

> **前提**: 需确认 `_i18n` 函数已在 elements.py 中定义（上游有，我们 fork 应该也有）。

---

## Commit 3: 0df7d85 — P0-07 deferred loading 补丁打在替身类（v1.4.0 最关键修复）{#commit-3}

### 修复 3.1: 抽取 `_apply_feishu_adapter_patches()` + deferred re-patch

| 项目 | 内容 |
|---|---|
| **文件** | `patching/__init__.py` + `patching/hermes_adapter.py` |
| **冲突风险** | **高** — 我们 fork 改了这两个文件（加了 approval card 相关的 adapter patch） |

### 根因
Hermes v0.17.0 引入 bundled platform deferred loading。插件 `apply_patches()` 在启动早期运行时，真身 `hermes_plugins.feishu_platform.adapter` 尚未加载，只能 patch 替身 `plugins.platforms.feishu.adapter`（源码路径）。gateway 启动后 deferred loader 触发加载真身，得到一个与替身不同的 class object → 早期 patch 形同虚设，clarify/delegate 卡片降级为纯文本。

### 修复方案
1. 抽取 `_apply_feishu_adapter_patches(FeishuAdapter, is_repatch=False)` 函数
2. 用 `id(cls)` 去重记录到 `_patched_feishu_classes` set
3. `_schedule_direct_patch` 新增 FeishuAdapter primary repatch（2s）+ secondary 兜底（10s）
4. `HermesCompat` 新增 `resolve_feishu_adapter_class_fresh()` 重新解析真身 class

### 3.1a: `patching/__init__.py` — `__all__` 新增导出

**行号**: 61（`'_patch_status'` 之后）

**改为**（在 `'_patch_status'` 之后添加）:
```python
    '_patch_status',
    # v1.4.0: FeishuAdapter patched-class registry (deferred loading fix)
    '_patched_feishu_classes',
```

**行号**: 69（`'_apply_direct_agent_patch'` 之后）

**改为**（在 `'_apply_direct_agent_patch'` 之后添加）:
```python
    '_apply_direct_agent_patch',
    # v1.4.0: FeishuAdapter patch helpers (deferred loading fix)
    '_apply_feishu_adapter_patches',
    '_apply_feishu_adapter_deferred_repatch',
    '_verify_feishu_patch_identity',
```

### 3.1b: `patching/__init__.py` — 新增 `_patched_feishu_classes` 模块级变量

**行号**: 166（`_patch_status = {}` 之后）

**改为**（在 `_patch_status = {}` 之后添加）:
```python
_patch_status: dict[str, Any] = {}

# ── FeishuAdapter patched-class registry (v1.4.0) ───────────────────
# hermes v0.17.0+ 引入 bundled platform deferred loading：插件 apply_patches()
# 在启动早期运行时，真身 hermes_plugins.feishu_platform.adapter 尚未加载，
# 只能 patch 替身 plugins.platforms.feishu.adapter（源码路径）。gateway 启动后
# deferred loader 触发加载真身，得到一个与替身不同的 class object → 早期 patch
# 形同虚设，clarify/delegate 卡片降级为纯文本。
#
# 此 set 用 id(cls) 记录所有已打过 patch 的 FeishuAdapter class 对象，配合
# _schedule_direct_patch 的延迟重打逻辑：2s 后（deferred loader 一般已完成）
# 重新 resolve 真身 class，若 id 不在 set 里则重新 patch（避免对同一个 class
# 重复打补丁）。详见 _apply_feishu_adapter_patches / _schedule_direct_patch。
_patched_feishu_classes: set[int] = set()
```

### 3.1c: `patching/__init__.py` — 抽取 `_apply_feishu_adapter_patches()`

**行号**: 436-519（当前 `apply_patches()` 中的 FeishuAdapter patch 块）

> ⚠️ **关键冲突点**: 我们 fork 在 FeishuAdapter patch 块中额外添加了 **approval card patches**（行 494-512: `send_exec_approval` + `_build_resolved_approval_card`）。抽取的 `_apply_feishu_adapter_patches()` 函数**必须保留这些 approval patches**。

**当前代码**（行 436-519）:
```python
    feishu_patched = False
    FeishuAdapter = compat.feishu_adapter_class
    if FeishuAdapter is not None:
        try:
            FeishuAdapter.send = _wrap_feishu_adapter_send(FeishuAdapter.send)
            # ... edit_message, reaction, clarify patches ...
            # ... approval patches (我们 fork 独有) ...
            feishu_patched = True
            _logger.info("hermes-lark-streaming: FeishuAdapter.send/edit/reaction/image/clarify patched ✓ ...")
        except AttributeError as e:
            _logger.info("hermes-lark-streaming: FeishuAdapter patch skipped (%s)", e)
    else:
        _logger.info("hermes-lark-streaming: FeishuAdapter not available via HermesCompat, patch skipped")
```

**改为**:
```python
    feishu_patched = False
    FeishuAdapter = compat.feishu_adapter_class
    if FeishuAdapter is not None:
        feishu_patched = _apply_feishu_adapter_patches(FeishuAdapter, is_repatch=False)
    else:
        _logger.info("hermes-lark-streaming: FeishuAdapter not available via HermesCompat, patch skipped")
```

**然后新增 `_apply_feishu_adapter_patches()` 函数**（在 `apply_patches()` 之后、`_schedule_direct_patch()` 之前）:

```python
def _apply_feishu_adapter_patches(FeishuAdapter, *, is_repatch: bool = False) -> bool:
    """Apply all FeishuAdapter method patches to the given class.

    v1.4.0: 抽取为独立函数，便于 _schedule_direct_patch 在 hermes v0.17.0+
    bundled platform deferred loading 完成后对真身 class 重新打补丁。
    用 id(FeishuAdapter) 去重，记录到 _patched_feishu_classes set。
    """
    if FeishuAdapter is None:
        return False

    cls_id = id(FeishuAdapter)
    if cls_id in _patched_feishu_classes:
        if is_repatch:
            _logger.debug(
                "hermes-lark-streaming: FeishuAdapter (class_id=%s) already patched, skip re-patch",
                cls_id,
            )
        return True

    try:
        FeishuAdapter.send = _wrap_feishu_adapter_send(FeishuAdapter.send)
        try:
            FeishuAdapter.edit_message = _wrap_feishu_adapter_edit(FeishuAdapter.edit_message)
        except AttributeError:
            _logger.debug("hermes-lark-streaming: FeishuAdapter.edit_message not found, edit interception skipped")
        try:
            FeishuAdapter.add_reaction = _wrap_feishu_adapter_add_reaction(FeishuAdapter.add_reaction)
        except AttributeError:
            try:
                FeishuAdapter._add_reaction = _wrap_feishu_adapter_add_reaction(FeishuAdapter._add_reaction)
            except AttributeError:
                _logger.debug("hermes-lark-streaming: FeishuAdapter.add_reaction/_add_reaction not found, reaction interception skipped")
        try:
            FeishuAdapter.delete_reaction = _wrap_feishu_adapter_delete_reaction(FeishuAdapter.delete_reaction)
        except AttributeError:
            try:
                FeishuAdapter._remove_reaction = _wrap_feishu_adapter_delete_reaction(FeishuAdapter._remove_reaction)
            except AttributeError:
                _logger.debug("hermes-lark-streaming: FeishuAdapter.delete_reaction/_remove_reaction not found, reaction interception skipped")

        # ── Clarify interactive card patches ──
        try:
            FeishuAdapter.send_clarify = _wrap_feishu_adapter_send_clarify(FeishuAdapter.send_clarify)
            _logger.info("hermes-lark-streaming: FeishuAdapter.send_clarify patched ✓ (clarify interactive card)")
        except AttributeError:
            _logger.debug("hermes-lark-streaming: FeishuAdapter.send_clarify not found, clarify card skipped")
        try:
            FeishuAdapter._on_card_action_trigger = _wrap_feishu_card_action_trigger(FeishuAdapter._on_card_action_trigger)
            _logger.info("hermes-lark-streaming: FeishuAdapter._on_card_action_trigger patched ✓ (clarify card callback)")
        except AttributeError:
            _logger.debug("hermes-lark-streaming: FeishuAdapter._on_card_action_trigger not found, clarify callback skipped")

        # ── Approval interactive card patches (我们 fork 独有) ──
        try:
            FeishuAdapter.send_exec_approval = _wrap_feishu_adapter_send_exec_approval(FeishuAdapter.send_exec_approval)
            _logger.info("hermes-lark-streaming: FeishuAdapter.send_exec_approval patched ✓ (approval CardKit 2.0 card)")
        except AttributeError:
            _logger.debug("hermes-lark-streaming: FeishuAdapter.send_exec_approval not found, approval card skipped")
        try:
            FeishuAdapter._build_resolved_approval_card = _wrap_feishu_adapter_build_resolved_approval(
                FeishuAdapter._build_resolved_approval_card
            )
            _logger.info("hermes-lark-streaming: FeishuAdapter._build_resolved_approval_card patched ✓ (approval resolved CardKit 2.0)")
        except AttributeError:
            _logger.debug("hermes-lark-streaming: FeishuAdapter._build_resolved_approval_card not found, resolved approval card skipped")

        # Record this class as patched AFTER successful patch
        _patched_feishu_classes.add(cls_id)
        _logger.info(
            "hermes-lark-streaming: FeishuAdapter.send/edit/reaction/image/clarify patched ✓ "
            "(gateway message cards enabled, class_id=%s)",
            cls_id,
        )
        return True
    except AttributeError as e:
        _logger.info("hermes-lark-streaming: FeishuAdapter patch skipped (%s)", e)
        return False
```

### 3.1d: `patching/__init__.py` — 新增 `_apply_feishu_adapter_deferred_repatch()` + `_verify_feishu_patch_identity()`

在 `_apply_feishu_adapter_patches()` 之后新增:

```python
def _apply_feishu_adapter_deferred_repatch(*, stage: str) -> None:
    """Re-resolve FeishuAdapter and re-patch if a new class object appears.

    v1.4.0: 内部辅助函数，供 _schedule_direct_patch 在延迟阶段调用。
    """
    try:
        new_cls = HermesCompat().resolve_feishu_adapter_class_fresh()
    except Exception as e:
        _logger.debug(
            "hermes-lark-streaming: FeishuAdapter deferred re-patch (%s) — resolve failed: %s",
            stage, e,
        )
        return

    if new_cls is None:
        _logger.debug(
            "hermes-lark-streaming: FeishuAdapter deferred re-patch (%s) — class still not resolvable, skip",
            stage,
        )
        return

    cls_id = id(new_cls)
    if cls_id in _patched_feishu_classes:
        _logger.debug(
            "hermes-lark-streaming: FeishuAdapter deferred re-patch (%s) — class_id=%s already patched, skip",
            stage, cls_id,
        )
        return

    _logger.info(
        "hermes-lark-streaming: FeishuAdapter deferred re-patch (%s) — new class_id=%s detected, applying patches",
        stage, cls_id,
    )
    ok = _apply_feishu_adapter_patches(new_cls, is_repatch=True)
    if ok:
        _logger.warning(
            "hermes-lark-streaming: FeishuAdapter re-patched on deferred-loaded class "
            "(v0.17.0+ bundled platform). This indicates hermes deferred loading "
            "created a separate class object."
        )


def _verify_feishu_patch_identity(adapter_instance: Any) -> bool:
    """Verify that an adapter instance's class has been patched by HLS.

    v1.4.0: 运行时身份校验。
    """
    if adapter_instance is None:
        return False
    cls = type(adapter_instance)
    cls_id = id(cls)
    if cls_id in _patched_feishu_classes:
        return True
    _logger.error(
        "HLS: FeishuAdapter identity mismatch! adapter instance class id=%s "
        "not in patched classes %s. Clarify/delegate cards will fall back to "
        "text. Run /aowen doctor.",
        cls_id, sorted(_patched_feishu_classes),
    )
    return False
```

### 3.1e: `patching/__init__.py` — 修改 `_schedule_direct_patch()` 新增 FeishuAdapter re-patch

**行号**: 551-562

**当前代码**:
```python
def _schedule_direct_patch() -> None:
    """Schedule _apply_direct_agent_patch to run after Hermes finishes loading."""
    import threading

    def _delayed_patch():
        import time
        time.sleep(2)  # Wait for Hermes to finish loading
        _apply_direct_agent_patch()

    t = threading.Thread(target=_delayed_patch, daemon=True)
    t.start()
    _logger.info("hermes-lark-streaming: scheduled direct agent patch (2s delay)")
```

**改为**:
```python
def _schedule_direct_patch() -> None:
    """Schedule _apply_direct_agent_patch + FeishuAdapter re-patch after Hermes finishes loading.

    v1.4.0: 除了原有的 2s 后 AIAgent.run_conversation 重打，新增 FeishuAdapter
    延迟重打 — hermes v0.17.0+ bundled platform deferred loading 场景下，
    apply_patches() 启动早期真身尚未加载，只能 patch 替身；2s 后 deferred
    loader 触发加载真身，此时必须重新 resolve 真身并 patch。

    调度策略:
      - t=2s: 第一轮 — AIAgent 重打 + FeishuAdapter 真身 re-patch
      - t=10s: 第二轮兜底 — 仅 FeishuAdapter re-patch
    """
    import threading

    def _delayed_patch():
        import time
        time.sleep(2)  # Wait for Hermes to finish loading
        _apply_direct_agent_patch()
        _apply_feishu_adapter_deferred_repatch(stage="primary")

        # 二次兜底：某些慢加载环境 deferred loading 可能延迟更久
        time.sleep(8)
        _apply_feishu_adapter_deferred_repatch(stage="secondary")

    t = threading.Thread(target=_delayed_patch, daemon=True)
    t.start()
    _logger.info("hermes-lark-streaming: scheduled direct agent patch (2s delay)")
    _logger.info(
        "hermes-lark-streaming: scheduled FeishuAdapter deferred re-patch "
        "(2s primary + 8s secondary fallback, v0.17.0+ bundled platform)"
    )
```

### 3.1f: `patching/__init__.py` — `inspect.signature` 防御

已在修复 2.6b 中覆盖。

### 3.1g: `patching/hermes_adapter.py` — 抽取 `_resolve_feishu_adapter()` + 新增 `resolve_feishu_adapter_class_fresh()`

| 项目 | 内容 |
|---|---|
| **冲突风险** | **高** — 我们 fork 的 `_resolve_feishu_adapter_class` 与上游的实现**完全不同** |

> ⚠️ **重要**: 我们 fork 的 `HermesCompat._resolve_feishu_adapter_class()` 实现比上游更复杂（含 `platform_registry` + `sys.modules` 回退），上游只有简单的 3 路径 import。我们**不需要**改我们的 `_resolve_feishu_adapter_class` 实现逻辑，只需要新增 `resolve_feishu_adapter_class_fresh()` 方法。

**当前代码**（行 83）:
```python
        self.feishu_adapter_class = self._resolve_feishu_adapter_class()
```

保持不变。

**新增**（在 `_resolve_feishu_adapter_class` 方法之后，行 141 附近）:
```python
    def resolve_feishu_adapter_class_fresh(self) -> Any | None:
        """Re-resolve FeishuAdapter class without reusing cached state.

        v1.4.0: 新增方法，供 _schedule_direct_patch 延迟重打阶段调用。
        每次 invoke 都重新跑 _resolve_feishu_adapter_class 解析逻辑（不复用
        self.feishu_adapter_class 缓存），返回当前 sys.modules 里能拿到的
        最新 class。
        """
        return self._resolve_feishu_adapter_class()
```

> **关键**: 我们 fork 的 `_resolve_feishu_adapter_class` 方法每次调用都会重新遍历 module_candidates + platform_registry + sys.modules，所以直接调用它即可实现 "fresh resolve"。

### 修复 3.2: delegate_task 后卡片降级纯文本 — 会话续写重激活（P0-2）

| 项目 | 内容 |
|---|---|
| **文件** | `controller/core.py` + `state/session.py` + `controller/linear_mixin.py` |
| **冲突风险** | 中-高（大量新代码，需仔细集成） |

> ⚠️ 这是 0df7d85 中最大的改动（+244 行 core.py）。如果当前场景不需要 delegate_task 续写功能，可以**暂缓**此修复，仅先做 3.1（deferred loading）。此修复逻辑独立，不影响 3.1。

#### 3.2a: `state/session.py` — 新增 slots + 初始化

**`__slots__`** 新增:
```python
        "_continuation_reactivation_count",
        "_is_continuation",
```

**`__init__`** 新增（在 `self._card_ready` 之后）:
```python
        self._is_continuation: bool = False
        self._continuation_reactivation_count: int = 0
```

#### 3.2b: `controller/core.py` — 新增 import + `_continuation_map` + 5 个新方法

**行 33 之后**新增 import:
```python
from ..state.linear import UnifiedLinearState
```

**`__init__`** 中新增（行 49 附近）:
```python
        self._continuation_map: dict[str, str] = {}
        self._continuation_map_lock = threading.Lock()
```

**新增方法**（在 `_fire_and_forget` 之前插入）:
- `_resolve_continuation_id(message_id) -> str | None`
- `_register_continuation(old, new) -> None`
- `_pop_continuation_id(message_id) -> str | None`
- `_reactivate_session_for_continuation(stale_session) -> CardSession | None`
- `_maybe_reactivate_for_continuation(message_id) -> str | None`

（完整代码见上游 diff，此处省略以节省篇幅 — 逻辑是：检测 `_streaming_closed=True` 且非终态的 session，创建新 continuation session，旧 session 异步收尾）

**`on_answer`** 开头新增重激活检查（行 312 之前）:
```python
        if text:
            new_id = self._maybe_reactivate_for_continuation(message_id)
            if new_id is not None:
                message_id = new_id
```

**`on_completed`** 中新增 continuation 重定向（行 539 之后）:
```python
        cont_id = self._pop_continuation_id(message_id)
        if cont_id is not None:
            message_id = cont_id
```

**`_cleanup`** 中新增 continuation map 清理（行 776 之后）:
```python
        with self._continuation_map_lock:
            self._continuation_map.pop(message_id, None)
            stale_cont_keys = [k for k, v in self._continuation_map.items() if v == message_id]
            for k in stale_cont_keys:
                del self._continuation_map[k]
```

#### 3.2c: `controller/linear_mixin.py` — `_do_create_linear_card` 不覆盖预置 `unified_state`

**行号**: 211

**当前代码**:
```python
        session.unified_state = UnifiedLinearState()
```

**改为**:
```python
        # v1.4.0 fix: 当本 session 是 continuation session 时，调用方可能已
        # 预创建 unified_state 并累积了 answer delta。仅当 None 时才创建。
        if session.unified_state is None:
            session.unified_state = UnifiedLinearState()
```

---

## 冲突风险总结 {#conflict-summary}

| 修复 | 文件 | 冲突风险 | 说明 |
|---|---|---|---|
| 1.1-1.3 | `controller/linear_mixin.py` | 低 | seal 分支结构一致，只需在合适位置插入 |
| 2.1 | `controller/core.py` | 低 | `on_message_started` 结构一致，但用 `self._sessions` 替代 `_sess_get` |
| 2.2 | `linear_mixin.py` + `session.py` | 低 | 新增 slot + 守卫逻辑 |
| 2.3 | `linear_mixin.py` | 低 | 新增 except 块 |
| 2.4 | `feishu/client.py` | 低 | 新增 import + except 分支 |
| 2.5 | `patching/gateway.py` | **中** | 三处 wrapper 结构需仔细对比 |
| 2.6 | `gateway.py` + `__init__.py` | 低 | try/except 包裹 |
| 2.7 | `linear_mixin.py` | 低 | 简单条件分支 |
| 2.8 | `linear_mixin.py` | 低 | 需确认 `bg_review_messages` 属性存在 |
| 2.9 | `flush/controller.py` | 低 | 新增 set + helper |
| 2.10 | `aowen/__init__.py` | 低 | 简单替换 |
| 2.11 | `cardkit/elements.py` | **中** | 我们 fork 用 `<details>` 格式，需保留格式但加 i18n |
| **3.1** | `patching/__init__.py` + `hermes_adapter.py` | **高** | 我们 fork 有 approval card patches，抽取函数时必须保留 |
| 3.2 | `core.py` + `session.py` + `linear_mixin.py` | **中-高** | 大量新代码，可暂缓 |

### 建议优先级

1. **必须先做**（P0 核心）: 3.1（deferred loading fix）— 这是 v1.4.0 最关键修复
2. **同时做**（P0/P1 独立修复）: 1.1-1.3, 2.1, 2.2, 2.4, 2.7
3. **第二批**（P1 防御性修复）: 2.3, 2.5, 2.6, 2.9, 2.10
4. **可选**（P2/i18n）: 2.8, 2.11
5. **可暂缓**（大功能）: 3.2（delegate_task 续写重激活）— 如当前不需要 delegate_task 功能

### 应用顺序建议

```
1. state/session.py          — 新增 _phase2_failed slot + init（2.2a）
2. controller/linear_mixin.py — 所有 Commit 1 + Commit 2 的 linear_mixin 改动
3. controller/core.py        — concurrency seal 复用（2.1）+ continuation（3.2 如需）
4. feishu/client.py          — 网络重试 + 频控码（2.4）
5. patching/gateway.py       — _msg_ctx 泄漏修复（2.5）+ inspect.signature（2.6a）
6. patching/__init__.py      — deferred loading（3.1）+ inspect.signature（2.6b）
7. patching/hermes_adapter.py — resolve_feishu_adapter_class_fresh（3.1g）
8. flush/controller.py       — Task 强引用（2.9）
9. aowen/__init__.py         — /aowen 异常处理（2.10）
10. cardkit/elements.py      — i18n_content（2.11）
```
