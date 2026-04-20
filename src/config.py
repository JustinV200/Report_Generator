"""Mode configuration — controls how much detail each pipeline stage produces."""


def get_mode_config(mode, num_sources):
    """Return a config dict for the given mode, scaled by *num_sources*."""
    base = {
        "brief": {
            "insights_per_source": 2,
            "max_themes": 3,
            "max_takeaways": 3,
            "section_depth": "1-2 sentences per point",
            "exec_summary": "1 short paragraph",
            "include_per_source_sections": False,
            "include_cross_source": False,
            "include_clusters": False,
            "cluster_threshold": None,
        },
        "standard": {
            "insights_per_source": 4,
            "max_themes": min(1 + num_sources, 3),
            "max_takeaways": min(1 + num_sources, 3),
            "section_depth": "2-3 sentences max per point — STOP when out of data, never pad with generic advice",
            "exec_summary": "2 short paragraphs (3-4 sentences each)",
            "include_per_source_sections": False,
            "include_cross_source": True,
            "include_clusters": num_sources >= 3,
            "cluster_threshold": "high",           # only the strongest connections
            "sectioned_generation": True,
        },
        "detailed": {
            "insights_per_source": 10,
            "max_themes": 4 + (num_sources * 2),
            "max_takeaways": 5 + num_sources,
            "section_depth": "2-3 paragraphs per point with examples, context, and implications",
            "exec_summary": "3-4 paragraphs",
            "include_per_source_sections": True,
            "include_cross_source": True,
            "include_clusters": num_sources >= 2,
            "cluster_threshold": "medium",         # high + medium relevance clusters
            "sectioned_generation": True,
        },
    }
    return base[mode]
