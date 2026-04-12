"""Analyzer — interprets extractions, clusters sources, and synthesizes cross-source insights."""

import json

from models import Model
from prompts.analysis import ANALYZE_PROMPT, CLUSTER_PROMPT, SYNTHESIZE_PROMPT


class Analyzer:
    """Analyze per-source extractions, cluster related sources, and synthesize themes."""

    def __init__(self, model=None, config=None):
        self.model = model or Model()
        self.config = config or {}

    def analyze(self, source_extraction):
        """Produce an interpretive analysis for a single source extraction."""
        prompt = ANALYZE_PROMPT.replace(
            "{insights_per_source}", str(self.config.get("insights_per_source", 5))
        )
        return self.model.call(prompt + json.dumps(source_extraction, indent=2))

    def cluster(self, analyses):
        """Identify clusters of related sources from their analyses."""
        return self.model.call(CLUSTER_PROMPT + json.dumps(analyses, indent=2))

    def synthesize(self, analyses, clusters):
        """Merge per-source analyses and clusters into a unified report blueprint."""
        include_clusters = self.config.get("include_clusters", False)
        cluster_threshold = self.config.get("cluster_threshold", "high")
        include_cross = self.config.get("include_cross_source", True)

        # Filter clusters by relevance threshold
        if clusters and include_clusters:
            thresholds = {"high": ["high"], "medium": ["high", "medium"], "low": ["high", "medium", "low"]}
            allowed = thresholds.get(cluster_threshold, ["high"])
            filtered = [c for c in clusters.get("clusters", []) if c.get("relevance") in allowed]
            cluster_instruction = json.dumps(filtered)
        else:
            cluster_instruction = "[]"

        cross_source_instruction = '[{"finding": "...", "type": "connection|contradiction|corroboration", "sources": ["..."]}]' if include_cross else "[]"

        prompt = SYNTHESIZE_PROMPT.format(
            max_themes=self.config.get("max_themes", 5),
            max_takeaways=self.config.get("max_takeaways", 5),
            exec_summary_instruction=self.config.get("exec_summary", "2-3 paragraphs") + " covering the most important findings across all sources",
            exec_summary_length=self.config.get("exec_summary", "2-3 paragraphs"),
            section_depth=self.config.get("section_depth", "1 paragraph per point"),
            cluster_instruction=cluster_instruction,
            cross_source_instruction=cross_source_instruction,
        )
        return self.model.call(prompt + json.dumps({"analyses": analyses, "clusters": clusters}, indent=2))

    def _group_by_clusters(self, analyses, clusters):
        """Group analyses using cluster relationships so related sources stay together."""
        if not clusters or not clusters.get("clusters"):
            # No clusters — split into groups of 3
            return [analyses[i:i+3] for i in range(0, len(analyses), 3)]

        # Build a name→analysis lookup
        by_name = {}
        for a in analyses:
            name = a.get("source_name", "")
            by_name[name] = a

        used = set()
        groups = []

        # Group by clusters first
        for c in clusters.get("clusters", []):
            group = []
            for src_name in c.get("sources", []):
                if src_name in by_name and src_name not in used:
                    group.append(by_name[src_name])
                    used.add(src_name)
            if group:
                groups.append(group)

        # Remaining analyses that weren't in any cluster
        remaining = [a for a in analyses if a.get("source_name", "") not in used]
        if remaining:
            for i in range(0, len(remaining), 3):
                groups.append(remaining[i:i+3])

        return groups

    def synthesize_map_reduce(self, analyses, clusters):
        """Map-reduce synthesis: synthesize in groups, then synthesize the sub-results."""
        max_per_group = 3

        if len(analyses) <= max_per_group:
            return self.synthesize(analyses, clusters)

        # Group analyses using cluster info
        groups = self._group_by_clusters(analyses, clusters)

        # Map: synthesize each group
        sub_syntheses = []
        for group in groups:
            sub = self.synthesize(group, clusters)
            sub_syntheses.append(sub)

        # Reduce: if we still have too many sub-syntheses, recurse
        if len(sub_syntheses) > max_per_group:
            # Wrap sub-syntheses as pseudo-analyses for the next round
            wrapped = []
            for s in sub_syntheses:
                wrapped.append({
                    "source_name": s.get("title", "Sub-synthesis"),
                    "source_summary": s.get("executive_summary", ""),
                    "key_insights": [{"insight": t.get("theme", "") + ": " + "; ".join(t.get("insights", [])), "supporting_stats": [], "significance": "high"} for t in s.get("themes", [])],
                    "trends": [],
                    "notable_claims": [],
                    "suggested_visuals": s.get("visualizations", []),
                    "unanswered_questions": [],
                })
            return self.synthesize_map_reduce(wrapped, None)

        # Final reduce: synthesize all sub-syntheses together
        wrapped = []
        for s in sub_syntheses:
            wrapped.append({
                "source_name": s.get("title", "Sub-synthesis"),
                "source_summary": s.get("executive_summary", ""),
                "key_insights": [{"insight": t.get("theme", "") + ": " + "; ".join(t.get("insights", [])), "supporting_stats": [], "significance": "high"} for t in s.get("themes", [])],
                "trends": [],
                "notable_claims": [],
                "suggested_visuals": s.get("visualizations", []),
                "unanswered_questions": [],
            })
        return self.synthesize(wrapped, clusters)

    def run(self, extractions):
        """Run the full analysis pipeline: per-source → clustering → synthesis."""
        # Phase 1: per-source analysis
        analyses = [self.analyze(ext) for ext in extractions]

        # Phase 2: cluster related sources (only if multiple sources)
        clusters = None
        if len(analyses) > 1 and self.config.get("include_clusters", False):
            clusters = self.cluster(analyses)

        # Phase 3: cross-source synthesis (map-reduce for large source sets)
        synthesis = self.synthesize_map_reduce(analyses, clusters)

        return {
            "per_source": analyses,
            "clusters": clusters,
            "synthesis": synthesis
        }