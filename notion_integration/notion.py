"""Notion API integration — push report summaries and full analyses to a Notion database."""

import requests
from dotenv import load_dotenv
import os

load_dotenv()

# GET API KEYS
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_BASE_URL = "https://api.notion.com/v1"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# Notion's rich_text property has a 2,000-character limit per block.
_RICH_TEXT_LIMIT = 2000


def _build_properties(extracted_data: dict) -> dict:
    """
    Build the Notion properties payload from extracted_data.

    Writes to two columns:
        Title   (title type)     — required
        Summary (rich_text type) — optional, truncated to 2,000 chars
    """
    title = str(extracted_data.get("title", "Untitled"))
    summary = str(extracted_data.get("summary", ""))[:_RICH_TEXT_LIMIT]

    properties = {
        "Title": {
            "title": [{"text": {"content": title}}]
        },
    }

    if summary:
        properties["Summary"] = {
            "rich_text": [{"text": {"content": summary}}]
        }

    return properties


def push_to_notion(extracted_data: dict) -> dict:
    """
    Push a report summary to the Notion database as a new row.

    Expected keys in extracted_data:
        title   (str)  The report title
        summary (str)  Short summary — truncated to 2,000 chars if longer

    Returns the Notion API response dict on success.
    Raises EnvironmentError if API credentials are missing.
    Raises requests.HTTPError if the Notion API returns an error.
    """
    if not NOTION_API_KEY:
        raise EnvironmentError("NOTION_API_KEY not found in Environment or .env file.")
    if not NOTION_DATABASE_ID:
        raise EnvironmentError("NOTION_DATABASE_ID not found in Environment or .env file.")

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": _build_properties(extracted_data),
    }

    response = requests.post(
        f"{NOTION_BASE_URL}/pages",
        headers=HEADERS,
        json=payload,
    )

    response.raise_for_status()
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


def _build_children(analysis: dict) -> list:
    """
    Convert the full analysis dict into a list of Notion block objects
    for the page body.

    Structure:
        Executive Summary  (heading + paragraphs)
        Themes             (heading + bullet per theme with its insights)
        Key Takeaways      (heading + numbered list)

    Stays within Notion's 100-block-per-request limit for typical reports.
    If the report exceeds 100 blocks, push_analysis_to_notion will split
    the remainder into a second append call.
    """
    synthesis = analysis.get("synthesis", {})
    blocks = []

    # --- Executive Summary ---
    blocks.append(_text_block("heading_2", "Executive Summary"))
    summary = synthesis.get("executive_summary", "")
    # Split into 2,000-char chunks in case the summary is long
    for i in range(0, max(1, len(summary)), _RICH_TEXT_LIMIT):
        chunk = summary[i:i + _RICH_TEXT_LIMIT]
        if chunk:
            blocks.append(_text_block("paragraph", chunk))

    # --- Themes ---
    themes = synthesis.get("themes", [])
    if themes:
        blocks.append(_text_block("heading_2", "Themes"))
        for theme in themes:
            theme_name = theme.get("theme", "")
            blocks.append(_text_block("heading_3", theme_name))
            for insight in theme.get("insights", []):
                blocks.append(_text_block("bulleted_list_item", str(insight)))

    # --- Key Takeaways ---
    takeaways = synthesis.get("key_takeaways", [])
    if takeaways:
        blocks.append(_text_block("heading_2", "Key Takeaways"))
        for takeaway in takeaways:
            blocks.append(_text_block("numbered_list_item", str(takeaway)))

    return blocks


def push_analysis_to_notion(analysis: dict) -> dict:
    """
    Convenience wrapper for the pipeline.

    Extracts title and executive_summary from the full analysis dict
    (the output of Analyzer.run()), pushes the row properties, and
    populates the page body with the full report content.

    Expected structure:
        analysis["synthesis"]["title"]             → Notion Title property
        analysis["synthesis"]["executive_summary"] → Notion Summary property + page body
        analysis["synthesis"]["themes"]            → page body
        analysis["synthesis"]["key_takeaways"]     → page body
    """
    synthesis = analysis.get("synthesis", {})

    extracted_data = {
        "title": synthesis.get("title", "Untitled Report"),
        "summary": synthesis.get("executive_summary", ""),
    }

    children = _build_children(analysis)

    # Notion allows max 100 blocks in a single create request
    first_batch = children[:100]
    overflow = children[100:]

    if not NOTION_API_KEY:
        raise EnvironmentError("NOTION_API_KEY not found in Environment or .env file.")
    if not NOTION_DATABASE_ID:
        raise EnvironmentError("NOTION_DATABASE_ID not found in Environment or .env file.")

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": _build_properties(extracted_data),
        "children": first_batch,
    }

    response = requests.post(
        f"{NOTION_BASE_URL}/pages",
        headers=HEADERS,
        json=payload,
    )
    response.raise_for_status()
    page = response.json()

    # Append any blocks that didn't fit in the initial request
    if overflow:
        page_id = page["id"]
        requests.patch(
            f"{NOTION_BASE_URL}/blocks/{page_id}/children",
            headers=HEADERS,
            json={"children": overflow},
        ).raise_for_status()

    return page