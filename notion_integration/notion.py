"""Notion API integration — push report summaries and full analyses to a Notion database."""

import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

# GET API KEYS
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion API limits
_RICH_TEXT_LIMIT = 2000          # max chars per rich_text block
_BLOCKS_PER_REQUEST = 100        # max children per create/append call
_REQUEST_TIMEOUT = 30            # seconds
_MAX_RETRIES = 3                 # for 429 / transient 5xx

# Notion's supported code-block languages (subset covering common cases).
# Anything not in this set falls back to "plain text" to avoid API errors.
_NOTION_CODE_LANGUAGES = {
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript", "c++",
    "c#", "css", "dart", "diff", "docker", "elixir", "elm", "erlang", "flow",
    "fortran", "f#", "gherkin", "glsl", "go", "graphql", "groovy", "haskell",
    "html", "java", "javascript", "json", "julia", "kotlin", "latex", "less",
    "lisp", "livescript", "lua", "makefile", "markdown", "markup", "matlab",
    "mermaid", "nix", "objective-c", "ocaml", "pascal", "perl", "php",
    "plain text", "powershell", "prolog", "protobuf", "python", "r", "reason",
    "ruby", "rust", "sass", "scala", "scheme", "scss", "shell", "sql", "swift",
    "typescript", "vb.net", "verilog", "vhdl", "visual basic", "webassembly",
    "xml", "yaml",
}


def _headers() -> dict:
    """Build request headers at call time so missing env vars surface clearly."""
    if not NOTION_API_KEY:
        raise EnvironmentError("NOTION_API_KEY not found in Environment or .env file.")
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _check_credentials() -> None:
    """Fail fast if Notion credentials are missing, before doing any work."""
    if not NOTION_API_KEY:
        raise EnvironmentError("NOTION_API_KEY not found in Environment or .env file.")
    if not NOTION_DATABASE_ID:
        raise EnvironmentError("NOTION_DATABASE_ID not found in Environment or .env file.")


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """
    Make a request to the Notion API with timeout and retry-on-429/5xx.

    Respects the Retry-After header when provided. Raises for any non-recoverable
    HTTP error on the final attempt.
    """
    kwargs.setdefault("timeout", _REQUEST_TIMEOUT)
    kwargs["headers"] = _headers()

    last_response = None
    for attempt in range(_MAX_RETRIES):
        response = requests.request(method, url, **kwargs)
        last_response = response

        # Rate limited or transient server error — back off and retry
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt == _MAX_RETRIES - 1:
                break
            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else 2 ** attempt
            except ValueError:
                wait = 2 ** attempt
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response

    # Exhausted retries
    last_response.raise_for_status()
    return last_response


def _build_properties(title: str, summary: str = "") -> dict:
    """
    Build the Notion properties payload.

    Writes to two columns:
        Title   (title type)     — required
        Summary (rich_text type) — optional, truncated to 2,000 chars
    """
    properties = {
        "Title": {
            "title": [{"text": {"content": title or "Untitled"}}]
        },
    }

    summary = (summary or "")[:_RICH_TEXT_LIMIT]
    if summary:
        properties["Summary"] = {
            "rich_text": [{"text": {"content": summary}}]
        }

    return properties


def check_push_to_notion_db(extracted_data: dict) -> dict:
    """
    Push a report summary to the Notion database as a new row.

    Used for testing the Notion connection without uploading a full report.

    Expected keys in extracted_data:
        title   (str)  The report title
        summary (str)  Short summary — truncated to 2,000 chars if longer

    Returns the Notion API response dict on success.
    Raises EnvironmentError if API credentials are missing.
    Raises requests.HTTPError if the Notion API returns an error.
    """
    _check_credentials()

    title = str(extracted_data.get("title", "Untitled"))
    summary = str(extracted_data.get("summary", ""))

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": _build_properties(title, summary),
    }

    response = _request_with_retry("POST", f"{NOTION_BASE_URL}/pages", json=payload)
    return response.json()


def _text_block(block_type: str, text: str) -> dict:
    """Build a single Notion block of the given type with plain text content."""
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": [{"type": "text", "text": {"content": text[:_RICH_TEXT_LIMIT]}}]
        },
    }


def _code_block(code: str, language: str = "plain text") -> dict:
    """Build a Notion code block with the given language."""
    if language.lower() not in _NOTION_CODE_LANGUAGES:
        language = "plain text"
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": code[:_RICH_TEXT_LIMIT]}}],
            "language": language,
        },
    }


def _parse_code_fence_language(fence_suffix: str) -> str:
    """
    Extract the language from a markdown code fence suffix.

    Handles plain (```python), Quarto-style (```{python}), and
    attribute-suffixed (```python {.callout}) fences. Falls back to
    "plain text" for anything not in Notion's supported language set.
    """
    stripped = fence_suffix.strip()
    if not stripped:
        return "plain text"

    # Quarto-style: {python} or {python, echo=false}
    brace_match = re.match(r'\{(\w+)', stripped)
    if brace_match:
        return brace_match.group(1)

    # Plain or attribute-suffixed: python, or python {.callout}
    word_match = re.match(r'(\w+)', stripped)
    if word_match:
        return word_match.group(1)

    return "plain text"


def _build_children(md_content: str) -> list:
    """
    Convert markdown text into a list of Notion block objects for the page body.

    Handles: headings (h1-h3), bullet lists, numbered lists, fenced code blocks,
    and paragraphs. Skips YAML frontmatter if present.

    Long text is split into 2,000-char chunks to stay within Notion's rich_text
    limit. Callers are responsible for batching blocks into groups of 100 per
    API request.
    """
    lines = md_content.split('\n')
    blocks = []
    i = 0

    # Skip YAML frontmatter (--- … ---)
    if lines and lines[0].strip() == '---':
        i = 1
        while i < len(lines) and lines[i].strip() != '---':
            i += 1
        i += 1  # skip closing ---

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Empty line — skip
        if not stripped:
            i += 1
            continue

        # Fenced code block
        if stripped.startswith('```'):
            lang = _parse_code_fence_language(stripped[3:])
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # skip closing ```
            code_text = '\n'.join(code_lines)
            if code_text.strip():
                for j in range(0, len(code_text), _RICH_TEXT_LIMIT):
                    blocks.append(_code_block(code_text[j:j + _RICH_TEXT_LIMIT], lang))
            continue

        # Headings: # → heading_1, ## → heading_2, ### → heading_3
        heading_match = re.match(r'^(#{1,3})\s+(.+)$', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            blocks.append(_text_block(f"heading_{level}", heading_match.group(2)))
            i += 1
            continue

        # Bullet list item (- or *)
        bullet_match = re.match(r'^[-*]\s+(.+)$', stripped)
        if bullet_match:
            blocks.append(_text_block("bulleted_list_item", bullet_match.group(1)))
            i += 1
            continue

        # Numbered list item (1. 2. etc.)
        num_match = re.match(r'^\d+\.\s+(.+)$', stripped)
        if num_match:
            blocks.append(_text_block("numbered_list_item", num_match.group(1)))
            i += 1
            continue

        # Paragraph — accumulate consecutive non-structural lines
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            next_stripped = lines[i].strip()
            if (not next_stripped
                    or re.match(r'^#{1,3}\s+', next_stripped)
                    or re.match(r'^[-*]\s+', next_stripped)
                    or re.match(r'^\d+\.\s+', next_stripped)
                    or next_stripped.startswith('```')):
                break
            para_lines.append(next_stripped)
            i += 1

        para_text = ' '.join(para_lines)
        if para_text:
            for j in range(0, len(para_text), _RICH_TEXT_LIMIT):
                blocks.append(_text_block("paragraph", para_text[j:j + _RICH_TEXT_LIMIT]))

    return blocks


def _extract_title(lines: list, body_start: int) -> str:
    """Extract title from YAML frontmatter or the first heading."""
    title = None

    if lines and lines[0].strip() == '---':
        for idx in range(1, len(lines)):
            if lines[idx].strip() == '---':
                for fm_line in lines[1:idx]:
                    # Greedy match, then strip surrounding quotes after the fact
                    m = re.match(r'^title:\s*(.+?)\s*$', fm_line)
                    if m:
                        title = m.group(1).strip().strip('"\'')
                break

    if not title:
        for line in lines[body_start:]:
            m = re.match(r'^#{1,2}\s+(.+)$', line)
            if m:
                title = m.group(1).strip()
                break

    return title or "Untitled Report"


def _extract_summary(lines: list, body_start: int) -> str:
    """Extract the Executive Summary section, stopping at the next heading."""
    summary_parts = []
    in_summary = False

    for line in lines[body_start:]:
        if re.match(r'^#{1,3}\s+Executive Summary', line, re.IGNORECASE):
            in_summary = True
            continue
        if in_summary:
            if re.match(r'^#{1,3}\s+', line):
                break
            if line.strip():
                summary_parts.append(line.strip())

    return ' '.join(summary_parts)[:_RICH_TEXT_LIMIT]


def _append_blocks(page_id: str, blocks: list) -> None:
    """Append blocks to an existing page, batching to stay under Notion's 100-block limit."""
    for start in range(0, len(blocks), _BLOCKS_PER_REQUEST):
        batch = blocks[start:start + _BLOCKS_PER_REQUEST]
        _request_with_retry(
            "PATCH",
            f"{NOTION_BASE_URL}/blocks/{page_id}/children",
            json={"children": batch},
        )


def push_analysis_to_notion(md_path: str) -> dict:
    """
    Read a Markdown file and push its content to Notion as a new database page.

    The title is extracted from YAML frontmatter or the first heading.
    The summary is taken from the Executive Summary section (if present).
    The full markdown body becomes the page content blocks, batched into
    groups of 100 per API request as required by Notion.
    """
    _check_credentials()

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    lines = md_text.split('\n')

    # Determine where the body starts (after YAML frontmatter, if any)
    body_start = 0
    if lines and lines[0].strip() == '---':
        for idx in range(1, len(lines)):
            if lines[idx].strip() == '---':
                body_start = idx + 1
                break

    title = _extract_title(lines, body_start)
    summary = _extract_summary(lines, body_start)
    children = _build_children(md_text)

    # Create the page with the first batch of blocks
    first_batch = children[:_BLOCKS_PER_REQUEST]
    overflow = children[_BLOCKS_PER_REQUEST:]

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": _build_properties(title, summary),
        "children": first_batch,
    }

    response = _request_with_retry("POST", f"{NOTION_BASE_URL}/pages", json=payload)
    page = response.json()

    # Append the remaining blocks in 100-block batches
    if overflow:
        _append_blocks(page["id"], overflow)

    return page