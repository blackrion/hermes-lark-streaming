# Port 6 Features from openclaw-lark (TypeScript) to hermes-lark-streaming (Python)

## Context

The `hermes-lark-streaming` plugin already has Python implementations that partially mirror the
openclaw-lark TypeScript reference. Several features in the TS reference are either missing,
incomplete, or have subtle behavioral differences. This plan ports 6 features to close those gaps.

**Key finding from analysis**: Features 3 and 4 are **already fully ported** in the current
Python codebase. Feature 2 is partially ported but has significant gaps. Features 1, 5, and 6
have clear, actionable work items.

## Analysis

### Feature Status Summary

| # | Feature | Status | Effort |
|---|---------|--------|--------|
| 1 | Markdown table spacing optimization | **Missing** — Python lacks `<br>` table spacing, heading gap, code-block `<br>` wrapping | Medium |
| 2 | Tool icon mapping + parameter redaction | **Partially ported** — has descriptors + basic redaction, missing `-H` header redaction, paramKeys/summaryPatterns, sanitizeParamsForLog, URL sanitization | Medium-High |
| 3 | Reflush-on-conflict scheduling | **Already ported** ✅ — `FlushController` in `flush/controller.py` has full reflush logic, long-gap batching, throttle, `set_card_message_ready()` | None |
| 4 | Invalid image key cleanup | **Already ported** ✅ — `_strip_invalid_image_keys()` in `cardkit/md.py` | None |
| 5 | CardKit API fail-fast error code | **Partially ported** — `_check()` does fail-fast, but lacks structured `CardKitApiError` with `api`/`context` fields and success logging | Low |
| 6 | Footer cache hit rate calculation | **Bug + missing features** — cache hit rate formula is wrong, `_compact` uses uppercase K/M (TS uses lowercase), no two-line footer split | Low-Medium |

### Affected Files

| File | Changes |
|------|---------|
| `cardkit/md.py` | Feature 1: Add table spacing, heading gap, code-block `<br>` wrapping to `optimize_markdown_style()` |
| `state/tooluse.py` | Feature 2: Add `-H`/`--header` redaction, `paramKeys`/`summaryPatterns`, `sanitizeParamsForLog`, URL sanitization |
| `feishu/client.py` | Feature 5: Add `CardKitApiError` class, enhance `_check()` with `api`/`context`, add success logging |
| `cardkit/elements.py` | Feature 6: Fix cache hit rate formula, add `compact_number()` (lowercase), add two-line footer support |

### New Files
- None required — all changes fit within existing files.

### Dependencies
- No new external dependencies needed.
- Internal dependencies: `cardkit/md.py` ← `cardkit/cards.py` ← `cardkit/elements.py` (import chain)

### Risk Areas
1. **Markdown regex changes** (Feature 1): Table spacing regexes are complex and order-sensitive; wrong ordering can corrupt content. Must be tested with edge cases (nested tables, tables in lists, tables after code blocks).
2. **Redaction regex changes** (Feature 2): Adding `-H`/`--header` patterns must not over-redact legitimate content.
3. **Cache formula change** (Feature 6): Changing the formula will alter displayed percentages for all users.
4. **Compact number case** (Feature 6): TS uses lowercase `k`/`m`, Python uses uppercase `K`/`M`. Changing case is a visual breaking change for existing users.

---

## Phases

### Phase 1: Markdown Table Spacing Optimization (Feature 1) ⭐⭐⭐

- **Goal**: Port the CardKit v2 table spacing logic from TS `optimizeMarkdownStyle()` into Python `optimize_markdown_style()`.
- **Files**: `cardkit/md.py`
- **Source reference**: `/tmp/openclaw-lark-ref/src/card/markdown-style.ts` lines 27-86

#### Current State
The Python `optimize_markdown_style()` (lines 66-112) already does:
1. ✅ Code block extraction with placeholders
2. ✅ Heading demotion (H1→H4, H2-H6→H5, only when h1-h3 exist)
3. ✅ Code block restoration (plain, no `<br>`)
4. ✅ Excessive blank line compression
5. ✅ Invalid image key stripping

**Missing from TS reference** (all under `cardVersion >= 2` block, lines 46-80):
- ❌ Consecutive heading gap: `^(#{4,5} .+)\n{1,2}(#{4,5} )` → `$1\n<br>\n$2`
- ❌ Table spacing: 4 regex patterns for `<br>` before/after tables (lines 51-69)
- ❌ Code block restoration with `<br>` wrapping: `\n<br>\n${block}\n<br>\n` (line 73)

#### Steps

- [ ] **Step 1.1**: Add a `card_version` parameter to `optimize_markdown_style()` with default `2`.
  - Signature: `def optimize_markdown_style(text: str, card_version: int = 2) -> str:`
  - This allows callers to opt out of v2 spacing if needed (matching TS `cardVersion` param).
  - **Reasoning**: The TS version supports `cardVersion=1` for legacy cards; we should match this flexibility.

- [ ] **Step 1.2**: Add heading gap insertion (TS line 48).
  - Insert after heading demotion (after current line 97), before code block restoration.
  - Regex: `r"^(#{4,5} .+)\n{1,2}(#{4,5} )"` → `r"\1\n<br>\n\2"` with `re.MULTILINE`
  - **Reasoning**: Prevents headings from visually merging in CardKit v2.

- [ ] **Step 1.3**: Add table spacing `<br>` insertion (TS lines 51-69).
  - Insert after heading gap, before code block restoration.
  - Implement all 6 sub-patterns from the TS source in order:
    1. `r"^([^|\n].*)\n(\|.+\n)"` → `r"\1\n\n\2"` (non-table line → table: add blank line)
    2. `r"\n\n((?:\|.+[^\S\n]*\n?)+)"` → `r"\n\n<br>\n\n\1"` (before table block: insert `<br>`)
    3. Table block end: match `(?:^\|.+...)+` and append `\n<br>\n` unless followed by `---`, `#{4,5} `, `**`, or EOF (use a replacement function)
    4. `r"^((?!#{4,5} )(?!\\*\\*).+)\n\n(<br>)\n\n(\|)"` → `r"\1\n\2\n\3"` (text before table: collapse extra blank line)
    5. `r"^(\*\*.+)\n\n(<br>)\n\n(\|)"` → `r"\1\n\2\n\n\3"` (bold before table: keep blank after)
    6. `r"(\|[^\n]*\n)\n(<br>\n)((?!#{4,5} )(?!\\*\\*))"` → `r"\1\2\3"` (text after table: collapse extra blank line)
  - **Reasoning**: These are exactly the TS patterns; they must be applied in this exact order to avoid conflicts.
  - **Risk**: These regexes are complex. Must test with: tables in code blocks (should be untouched since code blocks are already extracted), tables after headings, tables after bold text, tables at document start/end.

- [ ] **Step 1.4**: Modify code block restoration to include `<br>` wrapping for v2 (TS line 72-74).
  - Current (line 100-101): `r = r.replace(f"{mark}{i}___", block)`
  - New (v2): `r = r.replace(f"{mark}{i}___", f"\n<br>\n{block}\n<br>\n")`
  - New (v1): `r = r.replace(f"{mark}{i}___", block)` (unchanged)
  - **Reasoning**: Code blocks need visual separation from surrounding text in CardKit v2.

- [ ] **Step 1.5**: Update the early-return guard (line 78).
  - Current: `if len(text) < 100 and not re.search(r'^#{1,6} |\n#{1,6} |```|!\[|\n{3,}', text):`
  - Add `|\|` to the pattern to also short-circuit when there are no tables.
  - **Reasoning**: Table regex processing is expensive; skip when no `|` present.

- **Done when**:
  - `optimize_markdown_style()` produces `<br>` tags before/after tables and code blocks
  - Heading gaps have `<br>` between consecutive headings
  - Existing behavior (heading demotion, blank line compression, image key stripping) unchanged
  - All existing tests pass

---

### Phase 2: Tool Parameter Redaction Enhancement (Feature 2) ⭐⭐⭐

- **Goal**: Port missing redaction patterns and tool descriptor fields from TS to the existing Python `state/tooluse.py`.
- **Files**: `state/tooluse.py`
- **Source reference**: `/tmp/openclaw-lark-ref/src/card/reasoning-utils.ts` (lines 17-81) and `/tmp/openclaw-lark-ref/src/card/tool-use-display.ts` (lines 38-169, 310-531)

#### Current State
The Python `state/tooluse.py` already has:
1. ✅ `_TOOL_DESCRIPTORS` list (11 entries, matching TS)
2. ✅ `redact_inline_secrets()` — handles inline assignments, auth headers, secret flags
3. ✅ `_sanitize_detail()` — handles path/search/url/command sanitizers
4. ✅ `_redact_paths()` — basename-only path reduction
5. ✅ `_build_display_block()` — JSON pretty-print with text fallback
6. ✅ `_basename_only()`, `_resolve_tool_descriptor()`, `_humanize_tool_name()`

**Missing from TS reference**:

##### 2a. `-H`/`--header` argument redaction (reasoning-utils.ts lines 19-20, 31-36)
- ❌ TS has `QUOTED_HEADER_ARG_RE` and `UNQUOTED_HEADER_ARG_RE` patterns
- ❌ These detect `-H 'Header-Name: value'` and `--header Header-Name: value` and redact the value if the header name is sensitive
- ❌ TS `shouldRedactHeaderValue()` logic: redact if sensitive name AND not exactly "Authorization" (which is handled by `AUTH_HEADER_SECRET_RE`)

##### 2b. Tool descriptor `paramKeys` and `summaryPatterns` (tool-use-display.ts lines 38-47, 68-169)
- ❌ TS descriptors have `paramKeys`, `summaryPatterns`, `summaryPreference`, `detailFromParams` fields
- ❌ Python descriptors only have `aliases`, `icon`, `title`, `sanitizer`, `no_result`
- ❌ These enable extracting tool detail from structured params rather than just the raw detail string

##### 2c. `sanitizeParamsForLog()` (reasoning-utils.ts lines 75-80)
- ❌ TS has a function that logs only param key names (no values) for safe logging
- ❌ Python has no equivalent

##### 2d. URL sanitization in command paths (tool-use-display.ts lines 496-515)
- ❌ TS `sanitizeUrlForDisplay()` strips username/password from URLs and redacts sensitive query params
- ❌ Python `_redact_paths()` just does basename — doesn't handle URLs

##### 2e. Sophisticated command path redaction (tool-use-display.ts lines 466-531)
- ❌ TS has `redactCommandPaths()` → `redactCommandToken()` → `redactPathAssignment()` → `redactStandalonePath()` chain
- ❌ Python `_redact_paths()` is a simpler single regex that doesn't handle `=` assignments within tokens or URL detection

#### Steps

- [ ] **Step 2.1**: Add `-H`/`--header` redaction patterns to `redact_inline_secrets()`.
  - Add two new compiled regexes at module level:
    - `_QUOTED_HEADER_ARG_RE = re.compile(r'((?:^|[\s"\'`])(?:-H|--header)\s+)([\'"])([A-Za-z0-9_-]+)(\s*:\s*)([^\'"]*)(\2)', re.IGNORECASE)`
    - `_UNQUOTED_HEADER_ARG_RE = re.compile(r'((?:^|[\s"\'`])(?:-H|--header)\s+)([A-Za-z0-9_-]+)(\s*:\s*)([^\s"\'`]+)', re.IGNORECASE)`
  - Add `_should_redact_header_value(name)` helper: returns True if `_SENSITIVE_NAME_RE.search(name)` AND not `name.lower() == "authorization"` (auth is handled by `_AUTH_HEADER_RE`).
  - Add replacement functions for each pattern that check `_should_redact_header_value`.
  - Chain them into `redact_inline_secrets()` after `_AUTH_HEADER_RE` sub, before `_SECRET_FLAG_RE` sub.
  - **Reasoning**: Commands like `curl -H 'X-Api-Key: secret123'` currently leak the secret value.
  - **Risk**: Must not redact non-sensitive headers like `Content-Type`, `Accept`.

- [ ] **Step 2.2**: Add `paramKeys` and `summaryPatterns` to `_TOOL_DESCRIPTORS`.
  - Extend each descriptor dict with optional `param_keys`, `summary_patterns`, `summary_preference`, and `detail_from_params` fields.
  - Port the field values from TS `TOOL_DESCRIPTORS` (lines 68-169).
  - Example for `read`/`open`:
    ```python
    {
        "aliases": ["read", "open"],
        "icon": "file-link-text_outlined",
        "title": "Read",
        "sanitizer": "path",
        "no_result": True,
        "param_keys": ["file_path", "path", "file"],
        "summary_patterns": [re.compile(r"^(?:read|open)\s+(?:file\s+)?(.+)$", re.IGNORECASE)],
        "summary_preference": ["code", "quoted", "matched", "line"],
    },
    ```
  - Add `_extract_detail_from_params(params, desc)` — checks `desc["param_keys"]` in order, returns first scalar text value.
  - Add `_extract_detail_from_summary(summary_text, desc)` — applies `summary_patterns` to extract detail from summary lines.
  - Wire these into `build_display_steps()` to populate `detail` when raw detail is empty but params are available.
  - **Reasoning**: Currently tool detail is only populated from the raw `detail` string passed to `record_start()`. With `paramKeys`, we can extract meaningful detail from structured tool parameters.
  - **Risk**: Need to ensure backward compatibility — `ToolStep.detail` is still the primary source; param extraction is a fallback.

- [ ] **Step 2.3**: Add `sanitize_params_for_log()` function.
  ```python
  def sanitize_params_for_log(params: dict[str, Any] | None) -> str:
      if not params or not isinstance(params, dict):
          return ""
      keys = list(params.keys())
      if not keys:
          return "{}"
      return "{" + ",".join(keys) + "}"
  ```
  - Add to `__all__`.
  - **Reasoning**: Safe logging of tool params without leaking secrets.

- [ ] **Step 2.4**: Enhance `_redact_paths()` with URL sanitization and `=` assignment handling.
  - Port the TS chain: `redactCommandPaths` → `redactCommandToken` → `redactPathAssignment` → `redactStandalonePath`.
  - In Python:
    - Split command string by whitespace (preserving whitespace).
    - For each token: strip surrounding `()"'`, check for `=` (split left/right, redact right as path), check for URL prefix (sanitize URL), check for path-like token (basename only).
    - `_sanitize_url_for_display(url)`: use `urllib.parse.urlparse` to strip userinfo and redact sensitive query params.
  - Replace the current simple `_redact_paths()` regex with this more sophisticated implementation.
  - **Reasoning**: Current `_redact_paths()` is too simple — it doesn't handle `=` assignments, URLs, or quoted tokens.
  - **Risk**: Must preserve the existing function signature and return type since it's called from `_sanitize_detail()`.

- **Done when**:
  - `redact_inline_secrets()` redacts `-H`/`--header` sensitive header values
  - Tool descriptors have `param_keys` and `summary_patterns`
  - `sanitize_params_for_log()` is available and tested
  - `_redact_paths()` handles URLs, `=` assignments, and quoted tokens
  - All existing tests pass

---

### Phase 3: CardKit API Fail-Fast Error Code (Feature 5) ⭐

- **Goal**: Add structured `CardKitApiError` with `api`/`context` fields and success logging to `feishu/client.py`.
- **Files**: `feishu/client.py`
- **Source reference**: `/tmp/openclaw-lark-ref/src/card/cardkit.ts` (lines 44-57), `/tmp/openclaw-lark-ref/src/card/card-error.ts` (lines 46-57)

#### Current State
The Python `feishu/client.py` already has:
1. ✅ `FeishuAPIError` class with `code`, `extract_sub_code()`, `extract_schema_detail()`
2. ✅ `_check()` static method that does fail-fast: `if not response.success(): raise FeishuAPIError(...)`
3. ✅ Transient error retry logic

**Missing from TS reference**:
- ❌ TS `CardKitApiError` has `api` and `context` fields for better error context
- ❌ TS `logCardKitResponse()` logs at INFO level on success (not just on failure)
- ❌ TS uses structured error message format: `cardkit ${api} FAILED: code=${code}, msg=${msg}, ${context}`

#### Steps

- [ ] **Step 3.1**: Add `CardKitApiError` class (subclass of `FeishuAPIError`).
  ```python
  class CardKitApiError(FeishuAPIError):
      """CardKit API error with structured context."""
      def __init__(self, message: str, *, code: int = 0, api: str = "", context: str = "") -> None:
          super().__init__(message, code)
          self.api = api
          self.context = context
  ```
  - Place it after `FeishuAPIError` definition (around line 97).
  - **Reasoning**: Maintains backward compatibility (subclass of `FeishuAPIError`) while adding structured fields.

- [ ] **Step 3.2**: Enhance `_check()` to accept optional `api` and `context` parameters.
  - Current signature: `def _check(response: Any, operation: str) -> None`
  - New signature: `def _check(response: Any, operation: str, *, api: str = "", context: str = "") -> None`
  - When `api` is provided, raise `CardKitApiError` instead of `FeishuAPIError`.
  - Error message format: `f"cardkit {api} FAILED: code={code}, msg={msg}, {context}"` when `api` is set.
  - When `api` is empty, fall back to existing behavior (backward compatible).
  - **Reasoning**: Callers that pass `api`/`context` get structured errors; existing callers are unaffected.

- [ ] **Step 3.3**: Add success logging to CardKit API methods.
  - In `cardkit_create`, `cardkit_stream_element`, `cardkit_update`, `cardkit_batch_update`, `cardkit_close_streaming`, `cardkit_update_summary`, `cardkit_extend_ttl`:
  - After `self._check(resp, "operation_name")` succeeds, add:
    ```python
    _logger.debug("cardkit %s OK: code=%s", "operation_name", getattr(resp, 'code', 0))
    ```
  - Use `debug` level (not `info` — the TS uses `info` but that's too noisy for production Python).
  - **Reasoning**: Currently there's no success logging, making it hard to trace API call sequences in logs.

- [ ] **Step 3.4**: Update `_check()` calls in CardKit methods to pass `api` and `context`.
  - Example for `cardkit_create`:
    ```python
    self._check(resp, "cardkit_create", api="card.create", context=f"cardId={card_id}")
    ```
  - Apply to all 7 CardKit methods with appropriate `api` and `context` strings from the TS source.
  - **Reasoning**: Provides structured error context for debugging.

- **Done when**:
  - `CardKitApiError` is available and carries `api`/`context` fields
  - `_check()` accepts optional `api`/`context` parameters
  - CardKit API methods pass structured context
  - Success path logs at debug level
  - All existing tests pass (backward compatible)

---

### Phase 4: Footer Cache Hit Rate + Two-Line Footer (Feature 6) ⭐

- **Goal**: Fix cache hit rate formula, add compact number formatting (lowercase), and implement two-line footer layout.
- **Files**: `cardkit/elements.py`
- **Source reference**: `/tmp/openclaw-lark-ref/src/card/builder.ts` (lines 202-306)

#### Current State
The Python `cardkit/elements.py` already has:
1. ✅ `_compact()` — but uses uppercase `K`/`M` (TS uses lowercase `k`/`m`)
2. ✅ `_render_footer_field()` — handles `status`, `elapsed`, `model`, `tokens`, `context`, `cache`, `cost`, `api_calls`, `history_offset`, `compression_exhausted`
3. ✅ `_build_footer_elements()` — builds footer from configured field layout

**Issues to fix**:

##### 4a. Cache hit rate formula is WRONG
- **Current** (line 1162): `hit_pct = int(cache_read / input_total * 100)`
  where `input_total = data.get("input_tokens", 0)`
- **TS reference** (builder.ts line 282-283):
  ```
  const total = read + write + inputVal;
  const hit = total > 0 ? Math.round((read / total) * 100) : 0;
  ```
- The denominator should be `cache_read + cache_write + input_tokens`, not just `input_tokens`.
- Also missing: `cache_write_tokens` in the display (TS shows `read/write` ratio).

##### 4b. Compact number case mismatch
- **Current** `_compact()`: returns `"1.2K"`, `"1.5M"` (uppercase)
- **TS** `compactNumber()`: returns `"1.2k"`, `"1.5m"` (lowercase)
- **Decision**: Keep uppercase `K`/`M` in the existing `_compact()` for backward compatibility, but add a new `_compact_number()` function that uses lowercase to match TS. Use the new function in the new two-line footer path. This avoids breaking existing footer rendering while enabling TS-compatible formatting for the new footer.

##### 4c. Two-line footer layout
- **Current**: Footer uses a single line per configured row (from `footer_fields` config).
- **TS**: Splits into primary line (status · elapsed · model) and detail line (tokens · cache · context).
- **Decision**: Add a new footer field name `"cache_v2"` that uses the corrected formula. Add a new footer rendering mode that splits fields into primary/detail lines. This is opt-in via config to avoid breaking existing setups.

#### Steps

- [ ] **Step 4.1**: Fix the `cache` footer field to use correct hit rate formula.
  - In `_render_footer_field()` for `name == "cache"` (line 1158-1167):
  - Read `cache_read = data.get("cache_read_tokens", 0) or 0`
  - Read `cache_write = data.get("cache_write_tokens", 0) or 0` (NEW — currently not read)
  - Read `input_total = data.get("input_tokens", 0) or 0`
  - Compute: `total = cache_read + cache_write + input_total`
  - Compute: `hit_pct = int(cache_read / total * 100) if total > 0 else 0`
  - Display: `f"{_compact(cache_read)}/{_compact(cache_write)} ({hit_pct}%)"` — shows read/write ratio instead of read/input
  - **Reasoning**: The current formula understates the cache hit rate because it doesn't account for cache write tokens in the denominator. The TS formula is the correct one.
  - **Risk**: This changes displayed percentages. Need to handle case where `cache_write_tokens` is missing (old data) — fall back to old formula or show just read%.

- [ ] **Step 4.2**: Add `_compact_number()` function (lowercase variant).
  ```python
  def _compact_number(n: int) -> str:
      """Compact number with lowercase suffix (matches TS compactNumber)."""
      if n >= 1_000_000:
          m = n / 1_000_000
          return f"{int(m)}m" if m >= 100 else f"{m:.1f}m"
      if n >= 1_000:
          k = n / 1_000
          return f"{int(k)}k" if k >= 100 else f"{k:.1f}k"
      return str(round(n))
  ```
  - Place after existing `_compact()` (line 1199).
  - Add to `__all__`.
  - **Reasoning**: TS uses lowercase `k`/`m`. Existing `_compact` uses uppercase and is used by other footer fields — we don't want to change those. New two-line footer uses the lowercase variant.

- [ ] **Step 4.3**: Add two-line footer support to `_build_footer_elements()`.
  - Add a `two_line: bool = False` parameter to `_build_footer_elements()`.
  - When `two_line=True`:
    - Split fields into primary (`status`, `elapsed`, `model`) and detail (`tokens`, `cache`, `context`).
    - Render as two separate lines joined by `\n`.
    - Use `_compact_number()` instead of `_compact()` for token/cache values.
  - When `two_line=False` (default): existing behavior unchanged.
  - Wire the `two_line` parameter through from `build_unified_complete_card()` → `_build_footer_elements()`.
  - Add a config option `footer.two_line: bool` in `config/reader.py` (default `False`).
  - **Reasoning**: The two-line footer is more readable on mobile. Making it opt-in avoids breaking existing layouts.
  - **Risk**: Must ensure the `two_line` parameter flows through `build_preservative_seal_actions()` as well.

- **Done when**:
  - Cache hit rate uses `cache_read + cache_write + input_tokens` as denominator
  - `_compact_number()` is available with lowercase suffixes
  - Two-line footer mode is available (opt-in via config)
  - Existing footer rendering is unchanged when `two_line=False`
  - All existing tests pass

---

## Features 3 & 4: Already Ported (No Action Needed)

### Feature 3: Reflush-on-conflict scheduling ✅
The Python `FlushController` (`flush/controller.py`) already implements:
- ✅ Mutex-guarded flush via `_flush_in_progress` flag
- ✅ Reflush-on-conflict via `_needs_reflush` flag (set when flush is in-progress and new data arrives)
- ✅ Long-gap batching via `LONG_GAP_MS` and `BATCH_AFTER_GAP_MS` constants
- ✅ Configurable throttle per mode (`CARDKIT_MS` vs `PATCH_MS`)
- ✅ `set_card_message_ready()` gate
- ✅ `wait_for_flush()` support
- ✅ `mark_completed()` / `set_throttle()`

The Python version is actually more complete than the TS reference — it adds thread safety via `call_soon_threadsafe` and lazy event loop resolution. No changes needed.

### Feature 4: Invalid image key cleanup ✅
The Python `_strip_invalid_image_keys()` (`cardkit/md.py` lines 55-63) already implements:
- ✅ Matching `![alt](value)` pattern
- ✅ Stripping when value doesn't start with `img_`
- ✅ Early return when `![` is not present

This is functionally identical to the TS `stripInvalidImageKeys()`. No changes needed.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Table spacing regexes corrupt content | High — could break all card rendering | Test with 20+ edge cases before merging; keep the early-return guard that skips processing for short text without tables |
| `-H` header redaction over-redacts | Medium — could redact non-sensitive headers | Only redact when header name matches `_SENSITIVE_NAME_RE` AND is not `Authorization` (handled separately) |
| Cache formula change alters user-visible percentages | Low-Medium — users may notice different cache hit rates | The new formula is more accurate; document the change in release notes |
| Compact number case change breaks visual consistency | Low — only affects new two-line footer | Keep existing `_compact()` unchanged; only use `_compact_number()` in the new two-line path |
| `optimize_markdown_style()` signature change breaks callers | Medium — `cards.py` and `elements.py` both call it | Add `card_version` as keyword arg with default `2`; existing callers don't need changes |

## Rollback Strategy

All changes are in 4 files with no structural/architectural changes:
1. `cardkit/md.py` — Revert `optimize_markdown_style()` to remove `<br>` logic
2. `state/tooluse.py` — Remove new regexes and descriptor fields
3. `feishu/client.py` — Remove `CardKitApiError` class and revert `_check()` signature
4. `cardkit/elements.py` — Revert cache formula and remove `_compact_number()`

Since no new files are created and no imports are changed, rollback is a simple git revert of the affected files.

## Testing Strategy

- **Unit tests**: Add test cases for each new function/behavior
- **Integration test**: Send a test message with markdown tables, tool calls, and cache metrics to verify end-to-end rendering
- **Regression**: Run existing test suite (`pytest`) to ensure no breaks
- **Manual**: Send messages with edge cases (empty tables, nested code blocks, commands with `-H` headers, etc.)

## Implementation Order

1. **Phase 1** (Feature 1) — `cardkit/md.py` — No dependencies on other phases
2. **Phase 2** (Feature 2) — `state/tooluse.py` — No dependencies on other phases
3. **Phase 3** (Feature 5) — `feishu/client.py` — No dependencies on other phases
4. **Phase 4** (Feature 6) — `cardkit/elements.py` — No dependencies on other phases

All 4 phases are independent and can be implemented in parallel or in any order.

Phases 3 and 4 (Features 5 and 6) are the simplest and can serve as warm-up tasks.

Phase 1 (Feature 1) is the highest-risk due to complex regex patterns.

Phase 2 (Feature 2) is the most extensive in terms of new code.
