import json
import os
import re
from datetime import date
from prompts.report import (
    REPORT_PROMPT, SECTION_PROMPT,
    PER_SOURCE_SECTION, CLUSTER_SECTION, CROSS_SOURCE_SECTION,
)


class reportMaker:
    def __init__(self, model=None, output_dir="reports", config=None):
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        self.model = model
        self.output_dir = output_dir
        self.config = config or {}

    @staticmethod
    def _extract_numbers(obj):
        """Recursively extract all numeric values from a nested dict/list structure."""
        nums = set()
        if isinstance(obj, dict):
            for v in obj.values():
                nums.update(reportMaker._extract_numbers(v))
        elif isinstance(obj, list):
            for item in obj:
                nums.update(reportMaker._extract_numbers(item))
        elif isinstance(obj, (int, float)):
            if obj != 0:
                nums.add(float(obj))
        elif isinstance(obj, str):
            cleaned = obj.replace(",", "").replace("%", "").replace("$", "").strip()
            try:
                val = float(cleaned)
                if val != 0:
                    nums.add(val)
            except (TypeError, ValueError):
                pass
        return nums

    @staticmethod
    def _matches_any_stat(value, all_stat_numbers):
        """Check if a numeric value appears (within 1% tolerance) in the extracted numbers."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if v == 0:
            return False
        for s in all_stat_numbers:
            if abs(v - s) / abs(s) <= 0.01:
                return True
        return False

    def _validate_visuals(self, visualizations, all_stats):
        """Filter out visualizations that fail basic quality checks.
        Strips individual fabricated data points, then checks remaining quality.
        Falls back to lighter checks if strict validation kills everything."""
        # Pre-extract all numeric values from raw stats for efficient matching
        all_numbers = set()
        for stat in all_stats:
            all_numbers.update(self._extract_numbers(stat))

        strict_valid = []
        light_valid = []
        for vis in visualizations:
            original_points = vis.get("data_points", [])
            if not original_points:
                continue

            # Light validation: 2+ non-zero data points (no stat matching)
            light_values = []
            for p in original_points:
                try:
                    light_values.append(float(p.get("value", 0)))
                except (TypeError, ValueError):
                    light_values.append(0)
            if len(original_points) >= 2 and not all(v == 0 for v in light_values):
                light_valid.append(vis)

            # Strict validation: strip points that don't match real stats
            if all_numbers:
                verified_points = []
                for p in original_points:
                    try:
                        v = float(p.get("value", 0))
                    except (TypeError, ValueError):
                        continue
                    if v == 0:
                        continue
                    if self._matches_any_stat(v, all_numbers):
                        verified_points.append(p)
                if len(verified_points) >= 2:
                    vis_copy = dict(vis)
                    vis_copy["data_points"] = verified_points
                    strict_valid.append(vis_copy)
            else:
                # No stats to check against — pass through light validation
                if vis in light_valid:
                    strict_valid.append(vis)

        # If strict validation killed everything but light found some, fall back
        if not strict_valid and light_valid:
            return light_valid
        return strict_valid

    def _fix_qmd(self, content):
        # Strip unresolved bracketed placeholders like [specific date], [city name], etc.
        content = re.sub(r'\[specific \w+(?:\s+\w+)*\]', '', content)
        content = re.sub(r'\[insert \w+(?:\s+\w+)*\]', '', content)
        # Strip orphaned units where the LLM left the unit but no number
        # e.g. "with % of" → "", "beyond weeks" → "", "approximately %" → ""
        content = re.sub(r'\bwith %\b', '', content)
        content = re.sub(r'\bapproximately %\b', '', content)
        content = re.sub(r'\babout %\b', '', content)
        content = re.sub(r'\b(\d+\s+)?% of individuals', lambda m: m.group(0) if m.group(1) else 'individuals', content)
        content = re.sub(r'\bbeyond \w+ (days|weeks|months|years)\b', '', content)
        content = re.sub(r'\bover \w+ (days|weeks|months|years)\b', lambda m: m.group(0) if m.group(0).split()[1].replace(',','').isdigit() else '', content)
        # Clean up leftover artifacts: "As of , " → removed, inline double spaces
        content = re.sub(r'\b(As of|In|On|By)\s*,\s', '', content)
        content = re.sub(r'(?<=\S)  +', ' ', content)
        # Clean up sentences that became empty or broken after stripping
        content = re.sub(r',\s*,', ',', content)
        content = re.sub(r'\s+\.', '.', content)
        # Ensure frontmatter delimiters exist
        if not content.startswith("---"):
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.strip() == "" and i > 0:
                    lines.insert(0, "---")
                    lines.insert(i + 1, "---")
                    break
            content = "\n".join(lines)
        return content

    def _build_frontmatter(self, analysis, output_format):
        title = analysis.get("synthesis", {}).get("title", "Report")
        return f"""---
title: "{title}"
author: "ReGen"
date: "{date.today().isoformat()}"
format:
  {output_format}:
    theme: darkly
    toc: true
    toc-depth: 2
    number-sections: true
    embed-resources: true
execute:
  echo: false
  warning: false
---
"""

    def _generate_section(self, instruction, data, depth):
        prompt = SECTION_PROMPT.format(
            section_depth=depth,
            section_instruction=instruction,
        ) + json.dumps(data, indent=2)
        return self.model.call_raw(prompt)

    def _generate_single_call(self, analysis, output_format):
        """Original single-call generation for brief/standard modes."""
        depth = self.config.get("section_depth", "1 paragraph per point")

        # Validate visualizations before sending to the LLM
        all_stats = analysis.get("_raw_stats", [])
        synthesis = analysis.get("synthesis", {})
        if synthesis.get("visualizations"):
            synthesis["visualizations"] = self._validate_visuals(synthesis["visualizations"], all_stats)

        per_source = ""
        if self.config.get("include_per_source_sections", False):
            per_source = PER_SOURCE_SECTION.format(section_depth=depth)

        cluster = ""
        if self.config.get("include_clusters", False) and analysis.get("clusters"):
            cluster = CLUSTER_SECTION.format(section_depth=depth)

        cross_source = ""
        if self.config.get("include_cross_source", True):
            cross_source = CROSS_SOURCE_SECTION

        prompt = REPORT_PROMPT.format(
            output_format=output_format,
            date=date.today().isoformat(),
            exec_summary=self.config.get("exec_summary", "2-3 paragraphs"),
            section_depth=depth,
            per_source_section=per_source,
            cluster_section=cluster,
            cross_source_section=cross_source,
        ) + json.dumps(analysis, indent=2)
        return self.model.call_raw(prompt)

    def _generate_sectioned(self, analysis, output_format):
        """Section-by-section generation for detailed mode — avoids hitting output token limits."""
        depth = self.config.get("section_depth", "2-3 paragraphs per point with examples, context, and implications")
        synthesis = analysis.get("synthesis", {})
        per_source = analysis.get("per_source", [])
        sections = []

        # Validate visualizations before using them
        all_stats = analysis.get("_raw_stats", [])
        if synthesis.get("visualizations"):
            synthesis["visualizations"] = self._validate_visuals(synthesis["visualizations"], all_stats)

        # Frontmatter
        sections.append(self._build_frontmatter(analysis, output_format))

        # Executive Summary
        sections.append(self._generate_section(
            f"Write ## Executive Summary. Expand this into {self.config.get('exec_summary', '3-4 paragraphs')}. "
            "Each paragraph should be 3-4 sentences MAX with specific numbers, dates, and entity names. "
            "Do NOT exceed the paragraph limit. "
            "NEVER output bracketed placeholders like [specific date] — omit the phrase if the value is unknown. "
            "CRITICAL: Only state what the data says — NEVER invert findings or guess missing numbers. "
            "If a number is missing, omit the claim entirely rather than writing a bare % or placeholder.",
            {"executive_summary": synthesis.get("executive_summary", ""), "narrative_frame": synthesis.get("narrative_frame", "")},
            depth
        ))

        # Per-source deep-dives
        if self.config.get("include_per_source_sections", False) and per_source:
            # Filter out unknown/empty sources
            valid_sources = [src for src in per_source if src.get("source_name", "").lower() not in ("unknown", "unknown source", "")]
            if valid_sources:
                sections.append("\n## Source Deep-Dives\n")
                for src in valid_sources:
                    sections.append(self._generate_section(
                        f"Write ### {src.get('source_name', 'Source')} deep-dive. "
                        "Write source_summary as an intro paragraph, expand each key_insight into a detailed paragraph, "
                        "include notable_claims with strength ratings, include trends as narrative, "
                        "and create ```{python} code blocks for any suggested_visuals using EXACT data_points. "
                        "Do NOT create charts where all values are zero. Do NOT use placeholder labels like 'Category 1'.",
                        src, depth
                    ))

        # Themes
        themes = synthesis.get("themes", [])
        max_themes = self.config.get("max_themes", len(themes))
        themes = themes[:max_themes]
        visuals = synthesis.get("visualizations", [])

        # Build a set of already-assigned visual indices to avoid duplicates
        assigned_visual_indices = set()

        def _match_visuals(theme, visuals):
            """Match visualizations to a theme by title/rationale substring OR keyword overlap with insights."""
            theme_name = theme.get("theme", "").lower()
            theme_sources = {s.lower() for s in theme.get("sources_involved", [])}
            # Collect keywords from theme insights
            theme_words = set(theme_name.split())
            for ins in theme.get("insights", []):
                if isinstance(ins, str):
                    theme_words.update(w.lower() for w in ins.split() if len(w) > 4)

            matched = []
            for idx, v in enumerate(visuals):
                if idx in assigned_visual_indices:
                    continue
                title = v.get("title", "").lower()
                rationale = v.get("rationale", "").lower()
                # Direct substring match on theme name
                if theme_name in rationale or theme_name in title:
                    matched.append(idx)
                    continue
                # Keyword overlap: 2+ non-trivial words from theme appear in title or rationale
                haystack = title + " " + rationale
                overlap = sum(1 for w in theme_words if w in haystack)
                if overlap >= 2:
                    matched.append(idx)
                    continue
                # Source overlap: chart rationale mentions a source involved in this theme
                if theme_sources and any(src in rationale for src in theme_sources):
                    matched.append(idx)

            return matched

        if themes:
            for ti, theme in enumerate(themes):
                matched_indices = _match_visuals(theme, visuals)
                assigned_visual_indices.update(matched_indices)
                theme_visuals = [visuals[i] for i in matched_indices]

                has_visuals = len(theme_visuals) > 0
                if has_visuals:
                    viz_instruction = (
                        "Render the ```{python} chart(s) FIRST using EXACT data_points, "
                        "then write 2-3 sentences interpreting what the chart shows. "
                        "The chart is the primary content."
                    )
                else:
                    viz_instruction = (
                        "No visualizations for this theme — write concise narrative prose with bullet points for data."
                    )

                if ti == 0:
                    sections.append(self._generate_section(
                        f"Write ## Themes as the section header, then write ### {theme.get('theme', '')} as the first subsection under it. "
                        f"{viz_instruction} "
                        "Write each insight as narrative prose (NOT as ### headers). "
                        "Use ### ONLY for the subsection title. "
                        "Reference sources by name. "
                        "STOP when out of data — do not pad.",
                        {"theme": theme, "visualizations": theme_visuals},
                        depth
                    ))
                else:
                    sections.append(self._generate_section(
                        f"Write ### {theme.get('theme', '')} subsection. "
                        f"{viz_instruction} "
                        "Write each insight as narrative prose (NOT as ### headers). "
                        "Use ### ONLY for the subsection title. "
                        "Reference sources by name. "
                        "STOP when out of data — do not pad.",
                        {"theme": theme, "visualizations": theme_visuals},
                        depth
                    ))

            # Distribute remaining unmatched visuals to first theme without a visual
            unmatched = [i for i in range(len(visuals)) if i not in assigned_visual_indices]
            # (these will fall through to the Additional Visualizations section below)

        # Source Connections (clusters)
        clusters = analysis.get("clusters")
        if self.config.get("include_clusters", False) and clusters:
            source_clusters = synthesis.get("source_clusters", [])
            if source_clusters:
                sections.append(self._generate_section(
                    "Write ## Source Connections. For each cluster, create a ### subsection. "
                    "Open with 1-2 sentences explaining the relationship, then use bullet points for each comparison point. "
                    "Reference sources by name. STOP when out of comparison points — do NOT pad with general commentary.",
                    {"source_clusters": source_clusters},
                    depth
                ))

        # Cross-Source Findings
        cross = synthesis.get("cross_source_findings", [])
        if self.config.get("include_cross_source", True) and cross:
            sections.append(self._generate_section(
                "Write ## Cross-Source Findings. For each finding, write a full paragraph with context, "
                "label as connection/contradiction/corroboration, reference sources by name.",
                {"cross_source_findings": cross},
                depth
            ))

        # Remaining visualizations not placed in themes
        remaining_visuals = [visuals[i] for i in range(len(visuals)) if i not in assigned_visual_indices]
        if remaining_visuals:
            sections.append(self._generate_section(
                "Write ## Additional Visualizations. Create ```{python} code blocks for each visualization using EXACT data_points. "
                "Do NOT duplicate any charts already generated in previous sections.",
                {"visualizations": remaining_visuals},
                depth
            ))

        # Key Takeaways
        takeaways = synthesis.get("key_takeaways", [])
        max_takeaways = self.config.get("max_takeaways", len(takeaways))
        takeaways = takeaways[:max_takeaways]
        if takeaways:
            sections.append(self._generate_section(
                "Write ## Key Takeaways as a numbered list. Expand each takeaway into 1-2 sentences with specific data points. "
                "Restate insights in NEW words — do NOT copy sentences verbatim from earlier sections.",
                {"key_takeaways": takeaways},
                depth
            ))

        return "\n\n".join(sections)

    def generate(self, analysis, report_name="report", output_format="html"):
        if self.config.get("sectioned_generation", False):
            # Multi-page: section-by-section to avoid output token limits
            qmd_content = self._fix_qmd(self._generate_sectioned(analysis, output_format))
        else:
            # Brief: single call
            qmd_content = self._fix_qmd(self._generate_single_call(analysis, output_format))

        output_path = os.path.join(self.output_dir, f"{report_name}.qmd")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(qmd_content)
        
        return output_path