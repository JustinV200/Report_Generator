# Prompts for the analysis stage (analyzer/analyzer.py)
# Three-step pipeline: per-source analysis → source clustering → cross-source synthesis.
# The synthesis output is the "blueprint" that the report writer formats into a .qmd.

# Per-source analysis: interprets a single source extraction.
# Produces insights, trends, claims with strength ratings, suggested
# visualizations, and unanswered questions. Scales insight count to
# the density of data via {insights_per_source}. Uses _source_id
# (the real URL or filepath) to derive an accurate source_name.
ANALYZE_PROMPT = """You are a data analyst. You are given a structured extraction (entities, statistics, claims, summary) from a single source document. Your job is NOT to re-extract — all the facts are already provided. Your job is to INTERPRET the data.

Return ONLY valid JSON in this exact format:
{
    "source_summary": "1 sentence identifying this source",
    "source_name": "a short descriptive name for this source (e.g. 'USA Today COVID-19 Report, Sep 2025')",
    "key_insights": [
        {"insight": "a meaningful interpretation of the data — write 2-3 full sentences explaining what the data means, why it matters, and what it implies", "supporting_stats": ["metric names that support this"], "significance": "high|medium|low"}
    ],
    "trends": ["any patterns, increases, decreases, or trajectories in the data"],
    "notable_claims": [
        {"claim": "the claim", "strength": "strong|moderate|weak", "reasoning": "why you rated it this way"}
    ],
    "suggested_visuals": [
        {"title": "chart title", "chart_type": "bar|line|pie|hbar|grouped_bar|scatter", "data_points": [{"label": "x", "value": 0}], "rationale": "why this visualization is useful"}
    ],
    "unanswered_questions": ["gaps or things the source doesn't address"]
}

RULES:
- Only suggest a visualization if 2+ related data points exist for it
- Every data_point.value MUST be an exact number copied from the extraction's statistics — never estimate, round, or invent a number
- Every data_point.label MUST describe what that number measures, using the same wording as the extraction
- If you cannot fill at least 2 data_points with real extracted numbers, do NOT suggest the visualization
- Do NOT put unrelated metrics in the same visualization
- Whenever you find 2+ comparable statistics (e.g. rates across age groups, counts over time, category breakdowns), include a suggested_visuals entry — prefer creating a visualization over leaving comparable numbers as text only
- Rate insight significance based on magnitude, novelty, and actionability
- Flag any statistics that seem implausible or lack context
- Keep all dates with full year
- Produce key_insights proportional to the data density — aim for roughly 1 insight per 2-3 statistics in the extraction, up to {insights_per_source} max
- If the source has very little data (few statistics, short summary), produce fewer insights — do NOT invent or stretch thin data
- A source with 2 statistics should produce 1-2 insights; a source with 20 statistics could produce {insights_per_source}
- If a _source_id field is present, use it to create a short, accurate source_name (e.g. for a URL, use the domain + page title; for a file path, use the filename). Do NOT invent a report title that doesn't exist

Source extraction:
"""

# Clustering: groups 2-3 related sources that share data, contradict
# each other, or cover the same event from different angles. Uses
# double-brace escaping for JSON format strings passed through .format().
CLUSTER_PROMPT = """You are given per-source analyses from multiple documents. Identify pairs or small groups (2-3) of sources that are closely related — they cover the same event, contradict each other, use the same data differently, or directly build on each other.

Return ONLY valid JSON in this exact format:
{{
    "clusters": [
        {{
            "cluster_name": "a descriptive name for this connection (e.g. 'CDC vs WHO Variant Tracking')",
            "sources": ["source_name values of the 2-3 sources in this cluster"],
            "relationship": "1 sentence explaining why these sources are related",
            "relevance": "high|medium|low",
            "shared_entities": ["entities that appear in multiple sources in this cluster"],
            "key_comparison_points": [
                "a specific point of agreement, disagreement, or complementary coverage — write 2-3 sentences with data"
            ]
        }}
    ]
}}

RULES:
- Only cluster sources that have a MEANINGFUL relationship — shared topic is not enough, they must have overlapping data, contradictory claims, or complementary perspectives
- A source can appear in multiple clusters
- Rate relevance: high = directly contradictory or complementary data, medium = same topic with different angles, low = loosely related
- Each cluster must have at least 2 key_comparison_points

Source analyses:
"""

# Cross-source synthesis: merges all per-source analyses + clusters into
# a single report blueprint. Produces title, exec summary, themes,
# visualizations, takeaways. Has many format placeholders filled at
# runtime by Analyzer.synthesize() — max_themes, max_takeaways,
# exec_summary_instruction, section_depth, cluster/cross-source instructions.
# Enforces distinct themes and data-dense writing.
SYNTHESIZE_PROMPT = """You are a senior data analyst. You are given individual analyses from multiple source documents, plus source clusters showing relationships between sources. Your job is to synthesize them into a single unified analysis that forms the blueprint for a report.

Return ONLY valid JSON in this exact format:
{{
    "title": "a descriptive title for a report covering all sources",
    "executive_summary": "{exec_summary_instruction}",
    "narrative_frame": "1 sentence that ties all themes together — NOT a thesis to prove, but an editorial lens to organize the report through",
    "themes": [
        {{
            "theme": "a topic or theme that emerges across sources",
            "insights": ["relevant insights — {section_depth}"],
            "sources_involved": ["source_name values that contributed"]
        }}
    ],
    "source_clusters": {cluster_instruction},
    "cross_source_findings": {cross_source_instruction},
    "visualizations": [
        {{"title": "chart title", "chart_type": "bar|line|pie|hbar|grouped_bar|scatter", "data_points": [{{"label": "x", "value": 0}}], "rationale": "why this chart matters in the overall narrative"}}
    ],
    "narrative_order": ["ordered list of theme names suggesting how the report should flow"],
    "key_takeaways": ["each takeaway must be a full sentence with specific data points — produce exactly {max_takeaways}"]
}}

RULES:
- Produce exactly {max_themes} themes
- Each theme MUST be meaningfully distinct — if two themes overlap in topic, merge them into one. Do NOT create near-duplicate themes like "Ethical Issues" and "Societal Ethics"
- executive_summary must be {exec_summary_length}
- Use each source's source_name (not "Source 1" or "Source 2") when referencing sources
- Actively look for connections between sources — shared entities, overlapping time periods, related metrics
- Flag contradictions explicitly with both sides cited
- Merge duplicate visualizations from individual analyses — pick the best version or combine data
- For each theme that contains comparable numeric data, prefer including a visualization. It is better to produce a chart that gets filtered downstream than to skip chartable data entirely
- Every visualization data_point.value MUST be an exact number from the source analyses — do NOT invent, estimate, or fabricate values. If no real numbers exist for a chart, omit it
- If the source data lacks enough real numbers for a visualization, set visualizations to an empty list [] rather than inventing data
- NEVER pad a visualization with made-up data points to reach a minimum count — only include data points backed by real extracted numbers
- NEVER invert or contradict what the data says — if source data says X > Y, the visualization must reflect that
- Order the narrative logically: most important themes first, supporting detail after
- If there is only one source, still produce themes and takeaways — set cross_source_findings and source_clusters to empty lists []
- Each key_takeaway must be a full sentence with specific data points, not a vague summary
- ALWAYS cite specific numbers, dates, percentages, and dollar amounts from the source data — never write vague statements like "growing concern" or "increasingly apparent" when concrete data exists
- If the source data lacks statistics for a point, say so briefly rather than padding with generic filler

Source analyses and clusters:
"""
