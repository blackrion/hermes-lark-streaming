#!/usr/bin/env python3
"""Quick functional tests for new absorbed features."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

# ── Test Table features ──
print("=" * 50)
print("Testing Table Features (← Gawg-AI)")
print("=" * 50)

from cardkit.table import parse_table, render_markdown_with_tables, _infer_column_type, contains_table

# Test 1: Basic table parsing
md = "| 姓名 | 年龄 | 分数 |\n| --- | --- | --- |\n| 张三 | 25 | 95.5 |\n| 李四 | 30 | 88 |\n"
tables = parse_table(md)
assert len(tables) == 1, f"Expected 1 table, got {len(tables)}"
t = tables[0]
assert len(t.headers) == 3, f"Expected 3 cols, got {len(t.headers)}"
assert t.headers[0].name == "姓名"
assert t.headers[1].data_type == "number", f"Expected number, got {t.headers[1].data_type}"
assert len(t.rows) == 2
print("✅ Test 1: Basic table parsing - PASS")

# Test 2: Column type inference
assert _infer_column_type(["25", "30", "40"]) == "number"
assert _infer_column_type(["hello", "world"]) == "text"
assert _infer_column_type(["95.5%", "88%", "100%"]) == "number"
assert _infer_column_type(["1,000", "2,000"]) == "number"
print("✅ Test 2: Column type inference - PASS")

# Test 3: Mixed content rendering (text + table interleaving)
mixed_md = "这是一个对比表格：\n\n| 方案 | 成本 | 周期 |\n| --- | --- | --- |\n| A | 1000 | 2 |\n| B | 2000 | 1 |\n\n以上是方案对比。"
elements = render_markdown_with_tables(mixed_md)
assert len(elements) == 3, f"Expected 3 elements, got {len(elements)}"
assert elements[0]["tag"] == "markdown", f"Expected markdown, got {elements[0]['tag']}"
assert elements[1]["tag"] == "table", f"Expected table, got {elements[1]['tag']}"
assert elements[2]["tag"] == "markdown", f"Expected markdown, got {elements[2]['tag']}"
print("✅ Test 3: Mixed content interleaving - PASS")

# Test 4: No table fallback
elements = render_markdown_with_tables("Hello world, no tables here.")
assert len(elements) == 1 and elements[0]["tag"] == "markdown"
print("✅ Test 4: No table fallback - PASS")

# Test 5: Table overflow downgrade
many = "\n\n".join([f"| C{i} |\n| --- |\n| v{i} |" for i in range(8)])
elements = render_markdown_with_tables(many, max_tables=5)
table_count = sum(1 for e in elements if e["tag"] == "table")
code_count = sum(1 for e in elements if e["tag"] == "markdown" and "```" in e.get("content", ""))
assert table_count == 5, f"Expected 5 tables, got {table_count}"
assert code_count >= 3, f"Expected >= 3 downgraded, got {code_count}"
print("✅ Test 5: Table overflow downgrade - PASS")

# Test 6: Table element structure (Card 2.0)
tbl_el = elements[1] if elements[1]["tag"] == "table" else [e for e in elements if e["tag"] == "table"][0]
assert "columns" in tbl_el
assert "rows" in tbl_el
assert tbl_el["columns"][0]["name"] == "col_0"
assert tbl_el["columns"][0]["data_type"] in ("text", "number")
print("✅ Test 6: Table element Card 2.0 structure - PASS")

# ── Test Attachment features ──
print()
print("=" * 50)
print("Testing Attachment Features (← baileyh8)")
print("=" * 50)

import importlib.util
spec = importlib.util.spec_from_file_location("attachments", os.path.join(os.path.dirname(__file__), "state", "attachments.py"))
attachments_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attachments_mod)
extract_attachment_summaries = attachments_mod.extract_attachment_summaries
build_attachment_summary_elements = attachments_mod.build_attachment_summary_elements

source = {
    "attachments": [
        {"type": "image", "name": "screenshot.png"},
        {"type": "audio", "filename": "recording.mp3"},
    ],
    "files": ["report.pdf"],
}
summaries = extract_attachment_summaries(source)
assert len(summaries) == 3, f"Expected 3, got {len(summaries)}"
assert summaries[0]["type"] == "image"
assert summaries[1]["type"] == "audio"
assert summaries[2]["type"] == "file"
print("✅ Test 7: Structured attachment detection - PASS")

text_summaries = extract_attachment_summaries({}, text="MEDIA: video_demo.mp4\nCheck /tmp/screenshot.jpg")
assert len(text_summaries) == 2, f"Expected 2, got {len(text_summaries)}"
print("✅ Test 8: Text media scanning - PASS")

elements = build_attachment_summary_elements(summaries)
assert len(elements) == 1
assert elements[0]["tag"] == "div"
print("✅ Test 9: Attachment element building - PASS")

# ── Test Approval Card ──
print()
print("=" * 50)
print("Testing Approval Card (← baileyh8)")
print("=" * 50)

from cardkit.special import build_approval_card
card = build_approval_card(tool_name="execute_command", description="Run: rm -rf /tmp/cache", approval_id="appr_123")
assert card["schema"] == "2.0"
body_elements = card["body"]["elements"]
# Should have: title div, description markdown, 2 column_sets with buttons
column_sets = [e for e in body_elements if e["tag"] == "column_set"]
assert len(column_sets) == 2, f"Expected 2 column_sets, got {len(column_sets)}"
buttons = []
for cs in column_sets:
    for col in cs["columns"]:
        buttons.extend(col["elements"])
assert len(buttons) == 4, f"Expected 4 buttons, got {len(buttons)}"
# Check deny button has danger type
deny_btn = [b for b in buttons if b["type"] == "danger"]
assert len(deny_btn) == 1, f"Expected 1 danger button, got {len(deny_btn)}"
# Check callback values
for btn in buttons:
    val = btn["behaviors"][0]["value"]
    assert val["approval_id"] == "appr_123"
    assert val["action"] in ("allow_once", "allow_session", "allow_always", "deny")
print("✅ Test 10: Approval card 4-button layout - PASS")

print()
print("🎉 ALL TESTS PASSED!")
