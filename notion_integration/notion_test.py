"""
Unit tests for notion.py

Covers every public and internal function with mocked HTTP calls so tests
run without Notion credentials.  Also includes an optional live integration
test behind the --live flag.

USAGE:
    python -m unittest notion_test               # fast, no network
    python notion_test.py                         # same
    python notion_test.py --live                  # hit real Notion API
"""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock, call

import notion as n

QUARTO_BIN = os.environ.get("QUARTO_BIN")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(status_code=200, json_data=None, headers=None):
    """Build a minimal mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


SAMPLE_MARKDOWN = """\
---
title: "Test Report"
author: "ReGen"
date: "2026-04-16"
---

## Executive Summary

Short summary of the report for testing purposes.

## Themes

### Theme A

- Bullet one
- Bullet two

### Theme B

1. Numbered one
2. Numbered two

## Code Example

```python
def hello():
    print("hello")
```

## Closing

Final paragraph.
"""

MARKDOWN_NO_FRONTMATTER = """\
# Standalone Title

## Executive Summary

Summary without frontmatter.

Some content here.
"""


# ---------------------------------------------------------------------------
# _build_properties
# ---------------------------------------------------------------------------

class TestBuildProperties(unittest.TestCase):

    def test_title_and_summary(self):
        props = n._build_properties("My Title", "My Summary")
        self.assertEqual(
            props["Title"]["title"][0]["text"]["content"], "My Title"
        )
        self.assertEqual(
            props["Summary"]["rich_text"][0]["text"]["content"], "My Summary"
        )

    def test_empty_title_defaults_to_untitled(self):
        props = n._build_properties("", "sum")
        self.assertEqual(
            props["Title"]["title"][0]["text"]["content"], "Untitled"
        )

    def test_none_title_defaults_to_untitled(self):
        props = n._build_properties(None, "sum")
        self.assertEqual(
            props["Title"]["title"][0]["text"]["content"], "Untitled"
        )

    def test_empty_summary_omitted(self):
        props = n._build_properties("T", "")
        self.assertNotIn("Summary", props)

    def test_none_summary_omitted(self):
        props = n._build_properties("T", None)
        self.assertNotIn("Summary", props)

    def test_summary_truncated_to_limit(self):
        long = "x" * 3000
        props = n._build_properties("T", long)
        content = props["Summary"]["rich_text"][0]["text"]["content"]
        self.assertEqual(len(content), n._RICH_TEXT_LIMIT)


# ---------------------------------------------------------------------------
# _text_block / _code_block
# ---------------------------------------------------------------------------

class TestBlockBuilders(unittest.TestCase):

    def test_text_block_structure(self):
        blk = n._text_block("paragraph", "hello")
        self.assertEqual(blk["type"], "paragraph")
        self.assertEqual(
            blk["paragraph"]["rich_text"][0]["text"]["content"], "hello"
        )

    def test_text_block_truncates(self):
        blk = n._text_block("paragraph", "a" * 3000)
        content = blk["paragraph"]["rich_text"][0]["text"]["content"]
        self.assertEqual(len(content), n._RICH_TEXT_LIMIT)

    def test_code_block_known_language(self):
        blk = n._code_block("x = 1", "python")
        self.assertEqual(blk["code"]["language"], "python")
        self.assertEqual(blk["code"]["rich_text"][0]["text"]["content"], "x = 1")

    def test_code_block_unknown_language_falls_back(self):
        blk = n._code_block("stuff", "brainfuck")
        self.assertEqual(blk["code"]["language"], "plain text")

    def test_code_block_truncates(self):
        blk = n._code_block("z" * 3000, "python")
        content = blk["code"]["rich_text"][0]["text"]["content"]
        self.assertEqual(len(content), n._RICH_TEXT_LIMIT)


# ---------------------------------------------------------------------------
# _parse_code_fence_language
# ---------------------------------------------------------------------------

class TestParseCodeFenceLanguage(unittest.TestCase):

    def test_plain(self):
        self.assertEqual(n._parse_code_fence_language("python"), "python")

    def test_quarto_style(self):
        self.assertEqual(n._parse_code_fence_language("{python}"), "python")

    def test_quarto_with_options(self):
        self.assertEqual(
            n._parse_code_fence_language("{python, echo=false}"), "python"
        )

    def test_attribute_suffix(self):
        self.assertEqual(
            n._parse_code_fence_language("python {.callout}"), "python"
        )

    def test_empty_returns_plain_text(self):
        self.assertEqual(n._parse_code_fence_language(""), "plain text")

    def test_whitespace_only_returns_plain_text(self):
        self.assertEqual(n._parse_code_fence_language("   "), "plain text")


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------

class TestExtractTitle(unittest.TestCase):

    def test_from_frontmatter(self):
        lines = ['---', 'title: "FM Title"', '---', '## Body Heading']
        self.assertEqual(n._extract_title(lines, body_start=3), "FM Title")

    def test_from_frontmatter_unquoted(self):
        lines = ['---', 'title: Plain Title', '---', '']
        self.assertEqual(n._extract_title(lines, body_start=3), "Plain Title")

    def test_from_heading_when_no_frontmatter(self):
        lines = ['# Heading Title', '', 'paragraph']
        self.assertEqual(n._extract_title(lines, body_start=0), "Heading Title")

    def test_h2_heading_fallback(self):
        lines = ['some text', '## Second-level Title', 'more']
        self.assertEqual(
            n._extract_title(lines, body_start=0), "Second-level Title"
        )

    def test_fallback_to_untitled(self):
        lines = ['just text', 'no headings here']
        self.assertEqual(n._extract_title(lines, body_start=0), "Untitled Report")

    def test_empty_input(self):
        self.assertEqual(n._extract_title([], body_start=0), "Untitled Report")


# ---------------------------------------------------------------------------
# _extract_summary
# ---------------------------------------------------------------------------

class TestExtractSummary(unittest.TestCase):

    def test_extracts_summary_section(self):
        lines = [
            '## Executive Summary',
            '',
            'Line one.',
            'Line two.',
            '',
            '## Next Section',
        ]
        result = n._extract_summary(lines, body_start=0)
        self.assertIn("Line one.", result)
        self.assertIn("Line two.", result)
        self.assertNotIn("Next Section", result)

    def test_no_summary_section(self):
        lines = ['## Introduction', 'Some text.']
        self.assertEqual(n._extract_summary(lines, body_start=0), "")

    def test_summary_truncated(self):
        lines = ['## Executive Summary', 'x' * 3000]
        result = n._extract_summary(lines, body_start=0)
        self.assertLessEqual(len(result), n._RICH_TEXT_LIMIT)

    def test_case_insensitive_heading(self):
        lines = ['## executive summary', 'Found it.']
        result = n._extract_summary(lines, body_start=0)
        self.assertIn("Found it.", result)


# ---------------------------------------------------------------------------
# _build_children  (markdown -> Notion blocks)
# ---------------------------------------------------------------------------

class TestBuildChildren(unittest.TestCase):

    def test_heading_levels(self):
        md = "# H1\n## H2\n### H3"
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0]["type"], "heading_1")
        self.assertEqual(blocks[1]["type"], "heading_2")
        self.assertEqual(blocks[2]["type"], "heading_3")

    def test_bullet_list(self):
        md = "- one\n- two\n* three"
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 3)
        for blk in blocks:
            self.assertEqual(blk["type"], "bulleted_list_item")

    def test_numbered_list(self):
        md = "1. first\n2. second"
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 2)
        for blk in blocks:
            self.assertEqual(blk["type"], "numbered_list_item")

    def test_code_block(self):
        md = "```python\nprint('hi')\n```"
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "code")
        self.assertEqual(blocks[0]["code"]["language"], "python")
        self.assertEqual(
            blocks[0]["code"]["rich_text"][0]["text"]["content"], "print('hi')"
        )

    def test_code_block_no_language(self):
        md = "```\nsome code\n```"
        blocks = n._build_children(md)
        self.assertEqual(blocks[0]["code"]["language"], "plain text")

    def test_paragraph(self):
        md = "Just a paragraph."
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "paragraph")

    def test_consecutive_paragraph_lines_merged(self):
        md = "line one\nline two\nline three"
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 1)
        content = blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
        self.assertEqual(content, "line one line two line three")

    def test_skips_yaml_frontmatter(self):
        md = "---\ntitle: T\n---\nParagraph after."
        blocks = n._build_children(md)
        para_blocks = [b for b in blocks if b["type"] == "paragraph"]
        self.assertEqual(len(para_blocks), 1)
        self.assertIn("Paragraph after.", para_blocks[0]["paragraph"]
                       ["rich_text"][0]["text"]["content"])

    def test_empty_input(self):
        self.assertEqual(n._build_children(""), [])

    def test_long_paragraph_chunked(self):
        md = "a" * 5000
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 3)  # 2000 + 2000 + 1000
        for blk in blocks:
            content = blk["paragraph"]["rich_text"][0]["text"]["content"]
            self.assertLessEqual(len(content), n._RICH_TEXT_LIMIT)

    def test_long_code_block_chunked(self):
        code = "x" * 4500
        md = f"```python\n{code}\n```"
        blocks = n._build_children(md)
        self.assertEqual(len(blocks), 3)  # 2000 + 2000 + 500
        for blk in blocks:
            self.assertEqual(blk["type"], "code")

    def test_full_sample_markdown(self):
        blocks = n._build_children(SAMPLE_MARKDOWN)
        types = [b["type"] for b in blocks]
        self.assertIn("heading_2", types)
        self.assertIn("heading_3", types)
        self.assertIn("bulleted_list_item", types)
        self.assertIn("numbered_list_item", types)
        self.assertIn("code", types)
        self.assertIn("paragraph", types)


# ---------------------------------------------------------------------------
# _check_credentials
# ---------------------------------------------------------------------------

class TestCheckCredentials(unittest.TestCase):

    @patch.object(n, "NOTION_API_KEY", None)
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    def test_missing_api_key(self):
        with self.assertRaises(EnvironmentError):
            n._check_credentials()

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", None)
    def test_missing_database_id(self):
        with self.assertRaises(EnvironmentError):
            n._check_credentials()

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    def test_valid_credentials(self):
        n._check_credentials()  # should not raise


# ---------------------------------------------------------------------------
# _request_with_retry
# ---------------------------------------------------------------------------

class TestRequestWithRetry(unittest.TestCase):

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.requests.request")
    def test_success_on_first_try(self, mock_req):
        mock_req.return_value = _fake_response(200, {"ok": True})
        resp = n._request_with_retry("GET", "https://example.com")
        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(mock_req.call_count, 1)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.time.sleep")
    @patch("notion.requests.request")
    def test_retries_on_429(self, mock_req, mock_sleep):
        mock_req.side_effect = [
            _fake_response(429, headers={"Retry-After": "1"}),
            _fake_response(200, {"ok": True}),
        ]
        resp = n._request_with_retry("GET", "https://example.com")
        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(mock_req.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.time.sleep")
    @patch("notion.requests.request")
    def test_retries_on_500(self, mock_req, mock_sleep):
        mock_req.side_effect = [
            _fake_response(502),
            _fake_response(200, {"ok": True}),
        ]
        resp = n._request_with_retry("GET", "https://example.com")
        self.assertEqual(resp.json(), {"ok": True})
        self.assertEqual(mock_req.call_count, 2)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.time.sleep")
    @patch("notion.requests.request")
    def test_exponential_backoff_without_retry_after(self, mock_req, mock_sleep):
        mock_req.side_effect = [
            _fake_response(429),
            _fake_response(429),
            _fake_response(200, {"ok": True}),
        ]
        n._request_with_retry("GET", "https://example.com")
        self.assertEqual(mock_sleep.call_args_list, [call(1), call(2)])

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.time.sleep")
    @patch("notion.requests.request")
    def test_raises_after_max_retries(self, mock_req, mock_sleep):
        mock_req.return_value = _fake_response(429)
        with self.assertRaises(Exception):
            n._request_with_retry("GET", "https://example.com")
        self.assertEqual(mock_req.call_count, n._MAX_RETRIES)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.requests.request")
    def test_raises_on_client_error(self, mock_req):
        mock_req.return_value = _fake_response(400)
        with self.assertRaises(Exception):
            n._request_with_retry("GET", "https://example.com")
        self.assertEqual(mock_req.call_count, 1)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.time.sleep")
    @patch("notion.requests.request")
    def test_invalid_retry_after_uses_exponential(self, mock_req, mock_sleep):
        mock_req.side_effect = [
            _fake_response(429, headers={"Retry-After": "not-a-number"}),
            _fake_response(200, {"ok": True}),
        ]
        n._request_with_retry("GET", "https://example.com")
        mock_sleep.assert_called_once_with(1)  # 2^0


# ---------------------------------------------------------------------------
# check_push_to_notion_db  (integration-level, mocked HTTP)
# ---------------------------------------------------------------------------

class TestCheckPushToNotionDb(unittest.TestCase):

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    @patch("notion.requests.request")
    def test_sends_correct_payload(self, mock_req):
        mock_req.return_value = _fake_response(200, {"id": "page-1"})
        data = {"title": "T", "summary": "S"}
        result = n.check_push_to_notion_db(data)

        self.assertEqual(result, {"id": "page-1"})
        _, kwargs = mock_req.call_args
        payload = kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "db-123")
        self.assertEqual(
            payload["properties"]["Title"]["title"][0]["text"]["content"], "T"
        )
        self.assertEqual(
            payload["properties"]["Summary"]["rich_text"][0]["text"]["content"], "S"
        )

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    @patch("notion.requests.request")
    def test_missing_keys_default(self, mock_req):
        mock_req.return_value = _fake_response(200, {"id": "page-2"})
        result = n.check_push_to_notion_db({})

        _, kwargs = mock_req.call_args
        payload = kwargs["json"]
        self.assertEqual(
            payload["properties"]["Title"]["title"][0]["text"]["content"],
            "Untitled",
        )

    @patch.object(n, "NOTION_API_KEY", None)
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    def test_raises_without_api_key(self):
        with self.assertRaises(EnvironmentError):
            n.check_push_to_notion_db({"title": "T"})


# ---------------------------------------------------------------------------
# push_analysis_to_notion  (integration-level, mocked HTTP)
# ---------------------------------------------------------------------------

class TestPushAnalysisToNotion(unittest.TestCase):

    def _write_temp_md(self, content):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return f.name

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    @patch("notion.requests.request")
    def test_creates_page_with_blocks(self, mock_req):
        mock_req.return_value = _fake_response(200, {"id": "page-10"})
        path = self._write_temp_md(SAMPLE_MARKDOWN)
        try:
            result = n.push_analysis_to_notion(path)
            self.assertEqual(result["id"], "page-10")

            # The first call should be a POST to create the page
            first_call = mock_req.call_args_list[0]
            self.assertEqual(first_call[0][0], "POST")
            payload = first_call[1]["json"]
            self.assertEqual(payload["parent"]["database_id"], "db-123")
            self.assertEqual(
                payload["properties"]["Title"]["title"][0]["text"]["content"],
                "Test Report",
            )
            self.assertIn("children", payload)
            self.assertGreater(len(payload["children"]), 0)
        finally:
            os.unlink(path)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    @patch("notion.requests.request")
    def test_extracts_summary_into_properties(self, mock_req):
        mock_req.return_value = _fake_response(200, {"id": "page-11"})
        path = self._write_temp_md(SAMPLE_MARKDOWN)
        try:
            n.push_analysis_to_notion(path)
            payload = mock_req.call_args_list[0][1]["json"]
            summary = payload["properties"]["Summary"]["rich_text"][0]["text"]["content"]
            self.assertIn("Short summary", summary)
        finally:
            os.unlink(path)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    @patch("notion.requests.request")
    def test_title_from_heading_when_no_frontmatter(self, mock_req):
        mock_req.return_value = _fake_response(200, {"id": "page-12"})
        path = self._write_temp_md(MARKDOWN_NO_FRONTMATTER)
        try:
            n.push_analysis_to_notion(path)
            payload = mock_req.call_args_list[0][1]["json"]
            title = payload["properties"]["Title"]["title"][0]["text"]["content"]
            self.assertEqual(title, "Standalone Title")
        finally:
            os.unlink(path)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    @patch("notion.requests.request")
    def test_overflow_blocks_appended_in_batches(self, mock_req):
        mock_req.return_value = _fake_response(200, {"id": "page-13"})
        # Generate markdown with >100 blocks (each bullet = 1 block)
        bullets = "\n".join(f"- item {i}" for i in range(150))
        md = f"# Title\n\n## Executive Summary\n\nSummary.\n\n{bullets}"
        path = self._write_temp_md(md)
        try:
            n.push_analysis_to_notion(path)
            # First call: POST to create page (up to 100 children)
            # Second call: PATCH to append overflow
            self.assertGreaterEqual(mock_req.call_count, 2)
            second_call = mock_req.call_args_list[1]
            self.assertEqual(second_call[0][0], "PATCH")
            self.assertIn("/blocks/page-13/children", second_call[0][1])
        finally:
            os.unlink(path)

    @patch.object(n, "NOTION_API_KEY", None)
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    def test_raises_without_credentials(self):
        path = self._write_temp_md("# T")
        try:
            with self.assertRaises(EnvironmentError):
                n.push_analysis_to_notion(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# _append_blocks
# ---------------------------------------------------------------------------

class TestAppendBlocks(unittest.TestCase):

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.requests.request")
    def test_batches_at_100(self, mock_req):
        mock_req.return_value = _fake_response(200)
        blocks = [n._text_block("paragraph", f"b{i}") for i in range(250)]
        n._append_blocks("page-99", blocks)
        self.assertEqual(mock_req.call_count, 3)  # 100 + 100 + 50

        for i, c in enumerate(mock_req.call_args_list):
            batch = c[1]["json"]["children"]
            if i < 2:
                self.assertEqual(len(batch), 100)
            else:
                self.assertEqual(len(batch), 50)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.requests.request")
    def test_single_batch_under_limit(self, mock_req):
        mock_req.return_value = _fake_response(200)
        blocks = [n._text_block("paragraph", "x") for _ in range(50)]
        n._append_blocks("page-99", blocks)
        self.assertEqual(mock_req.call_count, 1)

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch("notion.requests.request")
    def test_empty_blocks_no_request(self, mock_req):
        n._append_blocks("page-99", [])
        mock_req.assert_not_called()


# ---------------------------------------------------------------------------
# Quarto pipeline: render qmd -> md, then parse through Notion block builders
# ---------------------------------------------------------------------------

REPORTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "reports")
)
TEST_QMD = os.path.join(REPORTS_DIR, "test.qmd")


class TestQuartoRender(unittest.TestCase):
    """Render test.qmd to .md and verify the output."""

    @classmethod
    def setUpClass(cls):
        if not QUARTO_BIN:
            raise unittest.SkipTest("QUARTO_BIN not set in environment")
        if not os.path.isfile(QUARTO_BIN):
            raise unittest.SkipTest(f"Quarto not found at {QUARTO_BIN}")
        if not os.path.isfile(TEST_QMD):
            raise unittest.SkipTest(f"{TEST_QMD} does not exist")
        # Render once for all tests in this class
        cls.md_path = os.path.splitext(TEST_QMD)[0] + ".md"
        result = subprocess.run(
            [QUARTO_BIN, "render", TEST_QMD, "--to", "md",
             "--output", os.path.basename(cls.md_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise unittest.SkipTest(f"Quarto render failed: {result.stderr}")

    def test_md_file_created(self):
        self.assertTrue(os.path.isfile(self.md_path), "test.md was not created")

    def test_rendered_md_has_expected_content(self):
        with open(self.md_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Executive Summary", content)
        self.assertIn("Key Takeaways", content)
        self.assertIn("def score_risk", content)


class TestQuartoToNotionBlocks(unittest.TestCase):
    """Render test.qmd then parse the .md through _build_children."""

    @classmethod
    def setUpClass(cls):
        if not QUARTO_BIN:
            raise unittest.SkipTest("QUARTO_BIN not set in environment")
        if not os.path.isfile(QUARTO_BIN):
            raise unittest.SkipTest(f"Quarto not found at {QUARTO_BIN}")
        if not os.path.isfile(TEST_QMD):
            raise unittest.SkipTest(f"{TEST_QMD} does not exist")
        cls.md_path = os.path.splitext(TEST_QMD)[0] + ".md"
        subprocess.run(
            [QUARTO_BIN, "render", TEST_QMD, "--to", "md",
             "--output", os.path.basename(cls.md_path)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        with open(cls.md_path, "r", encoding="utf-8") as f:
            cls.md_content = f.read()
        cls.md_lines = cls.md_content.split("\n")

    def test_build_children_produces_all_block_types(self):
        blocks = n._build_children(self.md_content)
        types = [b["type"] for b in blocks]
        self.assertGreater(len(blocks), 0)
        self.assertIn("heading_2", types)
        self.assertIn("heading_3", types)
        self.assertIn("bulleted_list_item", types)
        self.assertIn("numbered_list_item", types)
        self.assertIn("code", types)
        self.assertIn("paragraph", types)

    def test_extract_title_from_rendered_md(self):
        title = n._extract_title(self.md_lines, body_start=0)
        self.assertIn("Sample Report", title)

    def test_extract_summary_from_rendered_md(self):
        summary = n._extract_summary(self.md_lines, body_start=0)
        self.assertIn("sample report", summary.lower())

    @patch.object(n, "NOTION_API_KEY", "key-abc")
    @patch.object(n, "NOTION_DATABASE_ID", "db-123")
    @patch("notion.requests.request")
    def test_push_rendered_md_mocked(self, mock_req):
        """Full pipeline: real Quarto render, mocked Notion push."""
        mock_req.return_value = _fake_response(200, {"id": "page-qmd"})
        result = n.push_analysis_to_notion(self.md_path)

        self.assertEqual(result["id"], "page-qmd")
        first_call = mock_req.call_args_list[0]
        self.assertEqual(first_call[0][0], "POST")
        payload = first_call[1]["json"]
        self.assertIn("Sample Report", payload["properties"]["Title"]
                       ["title"][0]["text"]["content"])
        self.assertGreater(len(payload["children"]), 0)


# ---------------------------------------------------------------------------
# Live integration tests (opt-in via --live flag)
# ---------------------------------------------------------------------------

class TestLiveIntegration(unittest.TestCase):
    """
    Hit the real Notion API.  Skipped unless --live is passed on the CLI.
    Requires NOTION_API_KEY and NOTION_DATABASE_ID in the environment.
    """

    @classmethod
    def setUpClass(cls):
        import sys
        if "--live" not in sys.argv:
            raise unittest.SkipTest("Live tests skipped (pass --live to enable)")
        sys.argv.remove("--live")

    def test_live_push_summary(self):
        data = {
            "title": "[TEST] Live Summary Push",
            "summary": "Automated test -- safe to delete.",
        }
        result = n.check_push_to_notion_db(data)
        self.assertIn("id", result)
        print(f"  Created page: {result['id']}")

    def test_live_push_analysis(self):
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as f:
                f.write(SAMPLE_MARKDOWN)
                path = f.name
            result = n.push_analysis_to_notion(path)
            self.assertIn("id", result)
            print(f"  Created page: {result['id']}")
        finally:
            if path and os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()