"""Prompt templates for the interactive edit stage (agent-driven report refinement).

The editor is an agent loop: the model is given the user's request plus a
description of the available actions (tools) and the current report state,
then returns a structured plan of which actions to invoke. Each action has
its own follow-up prompt used when executing that step.

Flow:
    1. PLAN_PROMPT  — model decides which action(s) to take
    2. Per-action execution prompts — model generates the new content
    3. Final .qmd is patched in-place and re-saved

Available actions the planner can choose from:
    - rewrite_section:  regenerate an existing section from analysis data
    - add_section:      insert a new section derived from analysis data
    - remove_section:   drop a section entirely
    - reformat_section: pure formatting change (no new LLM reasoning on data)
    - new_visualization: create a new ```{python} chart block
    - edit_visualization: modify an existing chart's style, type, or labels
    - reanalyze:        re-run analysis on the extractions with a new focus
                        (more expensive — only when the user asks for new insights
                         that aren't already in the analysis JSON)
"""

# ---------------------------------------------------------------------------
# PLANNER
# ---------------------------------------------------------------------------
# The planner decides what to do. It sees:
#   - the user's natural-language request
#   - the current list of section headers in the .qmd
#   - the keys/shape of the analysis JSON (so it knows what data is available)
#   - the list of visualizations currently in the report
#
# It returns a JSON plan: an ordered list of actions with parameters.
# Format placeholders: {user_request}, {section_list}, {analysis_keys},
# {visualization_list}.
PLAN_PROMPT = """You are a report editing agent. The user has an existing report and wants to modify it.

You have these actions available:

1. rewrite_section — regenerate an existing section using the analysis data plus the user's new instruction.
   Parameters: {{"section": "<exact section header>", "instruction": "<what to change>"}}

2. add_section — insert a new section at a given position using analysis data.
   Parameters: {{"title": "<new section header>", "after": "<existing section to insert after, or 'top'/'bottom'>", "instruction": "<what the section should contain>"}}

3. remove_section — delete a section entirely.
   Parameters: {{"section": "<exact section header>"}}

4. reformat_section — pure formatting change. Use this for reordering, changing list→prose, shortening, bullet→paragraph conversions. Does NOT change facts or add analysis.
   Parameters: {{"section": "<exact section header>", "instruction": "<formatting change only>"}}

5. new_visualization — create a new chart using real data from the analysis.
   Parameters: {{"section": "<section to place chart in>", "chart_type": "bar|line|pie|hbar|grouped_bar|scatter", "title": "<chart title>", "rationale": "<what the chart shows>"}}

6. edit_visualization — modify an existing chart (change type, color palette, labels, size).
   Parameters: {{"chart_title": "<title of chart to edit>", "instruction": "<what to change>"}}

7. reanalyze — ONLY use this when the user asks for insights, themes, or findings that are NOT already in the analysis JSON. This is expensive. Prefer rewrite_section when the needed information is already in the analysis.
   Parameters: {{"focus": "<what angle to re-analyze with>", "affected_sections": ["<sections that will need regeneration after>"]}}

8. ask_followup — the user's request is ambiguous or underspecified. Ask ONE clarifying question. Use this ONLY when you genuinely cannot pick a reasonable interpretation; prefer acting on the most literal interpretation when possible.
   Parameters: {{"question": "<the single question to ask the user>"}}

9. refuse — the request cannot be satisfied with the available data. Use this when the user asks for something the analysis/extractions do not support — e.g. a chart when there are no comparable numeric data points, a comparison when there is only one source, or a theme that has no supporting evidence. Explain WHY in plain language and mention what would be needed to satisfy the request.
   Parameters: {{"reason": "<1-3 sentence explanation of why this cannot be done, citing specific data gaps>"}}

ask_followup and refuse MUST be the only action in the actions list when used — do not combine them with other actions.

Return ONLY valid JSON in this exact format:
{{
    "reasoning": "1-2 sentences explaining your plan",
    "actions": [
        {{"type": "<action_name>", "params": {{...}}}}
    ]
}}

RULES:
- Prefer the smallest, cheapest action that satisfies the request
- Use reformat_section over rewrite_section when the change is purely presentational
- Only use reanalyze when the user explicitly asks for new analysis, new themes, or data angles that are not present in the current analysis
- Match section names EXACTLY as they appear in the current report — do not paraphrase
- If the user's request is ambiguous, pick the most literal interpretation — only use ask_followup when no reasonable interpretation exists
- Multiple actions may be needed for complex requests — list them in execution order
- Before using new_visualization, verify the analysis data actually contains 2+ comparable numeric data points. If it does not, use refuse instead of generating a fake chart
- Before using rewrite_section or add_section for a comparison/cross-source section, verify 2+ sources exist. If only one source, use refuse
- When in doubt between acting and refusing: refuse. Never fabricate data to satisfy a request

Current report sections:
{section_list}

Current visualizations:
{visualization_list}

Data inventory (what's actually available in the analysis):
{data_inventory}

Available analysis data keys:
{analysis_keys}

User request:
{user_request}
"""


# ---------------------------------------------------------------------------
# REWRITE SECTION
# ---------------------------------------------------------------------------
# Regenerate an existing section using the original analysis data slice plus
# the user's modification instruction. Reuses the same style rules as the
# normal report generation so the rewritten section matches the rest.
# Format placeholders: {section_title}, {user_instruction}, {section_depth}.
REWRITE_SECTION_PROMPT = """You are rewriting ONE section of a Quarto (.qmd) report based on a user's edit request.

Section to rewrite: {section_title}

User's change request: {user_instruction}

RULES:
- Return ONLY the raw .qmd markdown for this section — no frontmatter, no other sections
- Start with the appropriate ## or ### header matching the section level
- Use ```{{python}} for executable code blocks
- Reference sources by their actual name, never as "Source 1"
- NEVER fabricate data — every number, date, and fact must come from the provided data
- NEVER output bracketed placeholders like [specific date] — omit the phrase if the value is unknown
- STOP writing when you run out of extracted data points — do NOT pad with generic advice
- {section_depth}

VISUALIZATION RULES (if applicable):
- Use the EXACT data_points from visualization specs — do not invent data
- NEVER mix metrics with different units on the same chart
- Use plt.tight_layout() before plt.show()
- Set figure size with plt.figure(figsize=(10, 6))
- NEVER create a chart where all values are zero

Data for this section:
"""


# ---------------------------------------------------------------------------
# ADD SECTION
# ---------------------------------------------------------------------------
# Generate a brand-new section from analysis data. Used when the user wants
# a section that doesn't exist yet (e.g. "add a methodology section",
# "add a section comparing X and Y").
# Format placeholders: {section_title}, {user_instruction}, {section_depth}.
ADD_SECTION_PROMPT = """You are generating a NEW section for a Quarto (.qmd) report.

New section title: {section_title}

What the section should contain: {user_instruction}

RULES:
- Return ONLY the raw .qmd markdown for this section
- Start with ## {section_title} as the header
- Use ### for any subsections
- Use ```{{python}} for executable code blocks, matplotlib/seaborn for charts
- Reference sources by their actual name
- NEVER fabricate data — only use facts from the provided analysis data
- If the requested content cannot be supported by the provided data, return an empty string
- {section_depth}

Available analysis data:
"""


# ---------------------------------------------------------------------------
# REFORMAT SECTION
# ---------------------------------------------------------------------------
# Pure formatting change — the model is given the EXISTING section text and
# asked to reformat it without altering facts. Used for "make this shorter",
# "convert to bullets", "reorder points", etc.
# Output is raw text, NOT JSON.
# Format placeholders: {user_instruction}.
REFORMAT_SECTION_PROMPT = """You are reformatting an existing section of a Quarto (.qmd) report.

Reformat instruction: {user_instruction}

STRICT RULES:
- Do NOT add new facts, numbers, claims, or analysis
- Do NOT remove any facts, numbers, or citations — only change how they are presented
- Do NOT modify ```{{python}} code blocks — keep them byte-for-byte identical
- Preserve all source name references
- Preserve the ## or ### section header exactly
- Return ONLY the reformatted .qmd markdown — no explanation, no wrapping

Original section:
"""


# ---------------------------------------------------------------------------
# NEW VISUALIZATION
# ---------------------------------------------------------------------------
# Build a new ```{python} chart block. The model is given the available
# numeric data points from the analysis and asked to produce a single
# matplotlib/seaborn code block that uses only real extracted values.
# Format placeholders: {chart_type}, {chart_title}, {rationale}.
NEW_VISUALIZATION_PROMPT = """You are generating a new visualization for a Quarto (.qmd) report.

Chart type: {chart_type}
Chart title: {chart_title}
Rationale: {rationale}

Return ONLY a single ```{{python}} ... ``` code block — no markdown headers, no prose, no explanation.

RULES:
- Use matplotlib and/or seaborn — import both at the top of the block
- Use EXACT numeric values from the data below — never invent, estimate, or round
- Every label must be a real, descriptive name from the data (no "Category 1")
- The chart must have a title, axis labels, and plt.tight_layout() before plt.show()
- Set figure size with plt.figure(figsize=(10, 6))
- Use plt.barh for horizontal bar when labels are long
- If the available data is insufficient (fewer than 2 real data points, or all values are zero), return an empty string

Available data points:
"""


# ---------------------------------------------------------------------------
# EDIT VISUALIZATION
# ---------------------------------------------------------------------------
# Modify an existing chart's presentation (type, palette, labels, size) without
# changing the underlying data. The model is given the existing code block and
# the user's instruction, and returns a replacement code block.
# Format placeholders: {user_instruction}.
EDIT_VISUALIZATION_PROMPT = """You are modifying an existing ```{{python}} visualization block in a Quarto report.

Modification request: {user_instruction}

STRICT RULES:
- Do NOT change the underlying data values or labels
- Only change presentational aspects: chart type, colors/palette, figure size, axis labels, title styling, legend placement, orientation
- PRESERVE every import statement from the original block (matplotlib.pyplot as plt, seaborn as sns, pandas as pd, etc.) — the chart will fail to render without them
- PRESERVE plt.figure(...), plt.tight_layout(), and plt.show() calls
- Keep the chart's title descriptive of what the data shows
- Return a COMPLETE, self-contained ```{{python}} ... ``` code block that runs on its own — no explanation, no wrapping

Original code block:
"""


# ---------------------------------------------------------------------------
# REANALYZE
# ---------------------------------------------------------------------------
# Re-run analysis on the existing extractions with a new interpretive focus.
# Used when the user asks for insights, themes, or angles that are NOT in the
# current analysis JSON. Output matches the synthesis schema so downstream
# sectioned generation can consume it unchanged.
# Format placeholders: {focus}, {max_themes}, {max_takeaways}.
REANALYZE_PROMPT = """You are re-analyzing existing source extractions with a new interpretive focus requested by the user.

New analytical focus: {focus}

You have the original extractions (entities, statistics, claims, summaries) from every source. Re-interpret the same data through this new lens. Do NOT invent new facts — only re-organize and re-interpret what is already extracted.

Return ONLY valid JSON in this exact format:
{{
    "title": "updated report title reflecting the new focus",
    "executive_summary": "2-3 paragraphs framed around the new focus",
    "narrative_frame": "1 sentence describing the new organizing lens",
    "themes": [
        {{"theme": "...", "insights": ["..."], "sources_involved": ["source_name values"]}}
    ],
    "visualizations": [
        {{"title": "...", "chart_type": "bar|line|pie|hbar|grouped_bar|scatter", "data_points": [{{"label": "x", "value": 0}}], "rationale": "..."}}
    ],
    "narrative_order": ["ordered list of theme names"],
    "key_takeaways": ["full sentences with specific data points"]
}}

RULES:
- Produce exactly {max_themes} themes
- Produce exactly {max_takeaways} takeaways
- Every visualization data_point.value MUST be an exact number from the extractions — do NOT invent values
- If the requested focus cannot be supported by the available extractions, return empty themes/takeaways lists and explain in executive_summary
- Reference sources by their source_name, never as "Source 1"

Original extractions:
"""
