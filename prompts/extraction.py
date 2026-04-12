"""Prompt templates for the extraction stage (map-reduce pipeline)."""

# Prompts for the extraction stage (extractor/extractor.py)
# These handle the map-reduce pipeline: each chunk gets individually extracted,
# then results are consolidated via reduce into one extraction per source.

# Sent to the LLM for each text chunk. Asks for structured JSON with
# entities, statistics, claims, and a short summary. Enforces full-year
# dates and specificity in metric descriptions.
EXTRACT_PROMPT = """You are a data extraction assistant. Extract structured information from the following content.

Return ONLY valid JSON in this exact format:
{
    "entities": ["list of key entities, organizations, people mentioned"],
    "statistics": [
        {"metric": "name", "value": 0, "unit": "unit", "context": "full date with year, source, and what the number specifically measures"}
    ],
    "claims": [
        {"statement": "a key claim made", "evidence_quote": "supporting quote from text"}
    ],
    "summary": "2-3 sentence summary of this content"
}

RULES:
- Always include the FULL YEAR in any date (e.g. "September 6, 2021" not "week of Sep 6th")
- Be specific about what each metric measures — include who, what, where, when
- If the source is vague about a date or metric, note that in the context field

Content:
"""

# Used instead of EXTRACT_PROMPT when a chunk is tagged as a table.
# Same output schema, but the input is serialized table data.
TABLE_PROMPT = """You are a data extraction assistant. Analyze this table data and extract key statistics and insights.

Return ONLY valid JSON in the same format as above.

Table data:
"""

# Used during the reduce step to merge multiple chunk extractions into one.
# Deduplicates entities, merges stats, keeps only well-supported claims,
# and writes a single document-level summary.
REDUCE_PROMPT = """You are given extractions from multiple chunks of the same document.
Consolidate into a single extraction:
- Deduplicate entities
- Merge statistics (flag contradictions)
- Keep only well-supported claims
- Write one overall document summary

Return ONLY valid JSON in the same structured format.

Chunk extractions:
"""
