"""ReportEditor — agent loop that plans and executes edits to an existing .qmd report.

Consumes the artifacts saved by reportMaker (manifest, extractions, analysis,
section_map, report.qmd) and exposes a single `query()` method. The model acts
as a planner that picks one or more actions (rewrite_section, add_section,
reformat_section, new_visualization, edit_visualization, remove_section,
reanalyze, ask_followup, refuse) which are then executed in order.

Each query that makes changes bumps the .qmd to versions/report.vN.qmd so the
user can roll back.
"""

import json
import os
import re
import shutil
from datetime import datetime

from prompts.edit import (
    PLAN_PROMPT,
    REWRITE_SECTION_PROMPT,
    ADD_SECTION_PROMPT,
    REFORMAT_SECTION_PROMPT,
    NEW_VISUALIZATION_PROMPT,
    EDIT_VISUALIZATION_PROMPT,
    REANALYZE_PROMPT,
)


class EditorResponse:
    """Result of a query — either a message for the user or a record of changes applied."""

    def __init__(self, kind, message="", actions_applied=None, plan=None):
        # kind is one of: "applied", "followup", "refused", "noop"
        self.kind = kind
        self.message = message
        self.actions_applied = actions_applied or []
        self.plan = plan or {}

    def __str__(self):
        return f"[{self.kind}] {self.message}"


class ReportEditor:
    """Agent that plans and executes edits to a Quarto .qmd report.

    Uses the LLM as both planner (picks which actions to invoke) and content
    generator (produces the new .qmd fragments). Cross-references the saved
    extractions, analysis, and section_map to avoid re-running expensive
    upstream stages when the needed data is already present.
    """

    def __init__(self, run_dir, model, config=None, verbose=False):
        self.run_dir = run_dir
        self.model = model
        self.config = config or {}
        self.verbose = verbose

        # Load persisted pipeline artifacts. Extractions + section_map are
        # optional (older runs may not have them) so missing files are tolerated.
        self.manifest = self._load_json("manifest.json", default={})
        self.extractions = self._load_json("extractions.json", default=[])
        self.analysis = self._load_json("analysis.json", default={})
        self.section_map = self._load_json("section_map.json", default={})

        self.qmd_path = os.path.join(run_dir, "report.qmd")
        self.qmd = self._load_qmd()

        # Parse the current .qmd into sections and viz blocks. Recomputed after
        # every successful edit so subsequent queries see fresh state.
        self.sections = self._split_sections()
        self.visualizations = self._extract_viz_blocks()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, user_request):
        """Run one edit cycle: plan → (ask/refuse or execute) → save if changed."""
        plan = self._plan(user_request)
        actions = plan.get("actions", [])
        reasoning = plan.get("reasoning", "")

        if self.verbose:
            print(f"  Plan: {reasoning}")

        # Handle terminal actions first — these never modify the report.
        if not actions:
            return EditorResponse("noop", reasoning or "No changes identified.", plan=plan)

        first = actions[0]
        if first["type"] == "ask_followup":
            return EditorResponse(
                "followup",
                first.get("params", {}).get("question", "Could you clarify?"),
                plan=plan,
            )
        if first["type"] == "refuse":
            return EditorResponse(
                "refused",
                first.get("params", {}).get("reason", "Request cannot be satisfied."),
                plan=plan,
            )

        # Execute normal edit actions in order.
        applied = []
        for action in actions:
            try:
                self._dispatch(action)
                applied.append(action["type"])
            except Exception as e:
                if self.verbose:
                    print(f"  Action {action['type']} failed: {e}")

        if applied:
            self._save_new_version()
            # Refresh in-memory state so a follow-up query sees the latest.
            self.qmd = self._load_qmd()
            self.sections = self._split_sections()
            self.visualizations = self._extract_viz_blocks()

        return EditorResponse(
            "applied" if applied else "noop",
            reasoning,
            actions_applied=applied,
            plan=plan,
        )

    # ------------------------------------------------------------------
    # Planner
    # ------------------------------------------------------------------

    def _plan(self, user_request):
        """Ask the LLM which action(s) to take given the current report state."""
        section_titles = [s["title"] for s in self.sections]
        viz_titles = [v["title"] for v in self.visualizations]
        prompt = PLAN_PROMPT.format(
            user_request=user_request,
            section_list=json.dumps(section_titles, indent=2),
            visualization_list=json.dumps(viz_titles, indent=2),
            data_inventory=json.dumps(self._data_inventory(), indent=2),
            analysis_keys=json.dumps(self._analysis_shape(), indent=2),
        )
        return self.model.call(prompt)

    def _data_inventory(self):
        """Summarize what's actually available — used by the planner to decide
        whether to refuse a request. Counts are cheap; the planner uses them to
        avoid suggesting charts when no numbers exist, etc."""
        synthesis = self.analysis.get("synthesis", {}) or {}
        per_source = self.analysis.get("per_source", []) or []
        raw_stats = self.analysis.get("_raw_stats", []) or []
        clusters = self.analysis.get("clusters") or {}
        numeric_stats = [s for s in raw_stats if isinstance(s, dict) and s.get("value") not in (None, 0, "")]
        return {
            "num_sources": len(per_source) or len(self.extractions),
            "num_statistics": len(raw_stats),
            "num_numeric_statistics": len(numeric_stats),
            "num_themes": len(synthesis.get("themes", []) or []),
            "num_visualizations_in_analysis": len(synthesis.get("visualizations", []) or []),
            "num_cross_source_findings": len(synthesis.get("cross_source_findings", []) or []),
            "num_clusters": len((clusters.get("clusters") if isinstance(clusters, dict) else []) or []),
            "has_extractions": bool(self.extractions),
        }

    def _analysis_shape(self):
        """Return the top-level keys of the analysis JSON (not the contents)."""
        synthesis = self.analysis.get("synthesis", {}) or {}
        return {
            "synthesis": list(synthesis.keys()),
            "per_source": ["source_name", "key_insights", "trends", "notable_claims", "suggested_visuals"] if self.analysis.get("per_source") else [],
            "clusters": bool(self.analysis.get("clusters")),
        }

    # ------------------------------------------------------------------
    # Action dispatcher
    # ------------------------------------------------------------------

    def _dispatch(self, action):
        handlers = {
            "rewrite_section":    self._rewrite_section,
            "add_section":        self._add_section,
            "remove_section":     self._remove_section,
            "reformat_section":   self._reformat_section,
            "new_visualization":  self._new_visualization,
            "edit_visualization": self._edit_visualization,
            "reanalyze":          self._reanalyze,
        }
        handler = handlers.get(action["type"])
        if not handler:
            raise ValueError(f"Unknown action type: {action['type']}")
        handler(**action.get("params", {}))

    # ------------------------------------------------------------------
    # Action: rewrite an existing section using its original data slice
    # ------------------------------------------------------------------

    def _rewrite_section(self, section, instruction):
        sec = self._find_section(section)
        if not sec:
            raise ValueError(f"Section not found: {section}")

        data = self._data_for_section(sec["title"])
        depth = self.config.get("section_depth", "2-3 sentences per point")
        prompt = REWRITE_SECTION_PROMPT.format(
            section_title=sec["title"],
            user_instruction=instruction,
            section_depth=depth,
        ) + json.dumps(data, indent=2)
        new_content = self.model.call_raw(prompt).strip()
        if not new_content:
            return
        self._replace_section(sec, new_content)

    # ------------------------------------------------------------------
    # Action: insert a brand-new section
    # ------------------------------------------------------------------

    def _add_section(self, title, after, instruction):
        depth = self.config.get("section_depth", "2-3 sentences per point")
        # Default to sending the whole synthesis — cheaper than asking the
        # planner to specify data paths for a section that doesn't exist yet.
        data = self.analysis.get("synthesis", {})
        prompt = ADD_SECTION_PROMPT.format(
            section_title=title,
            user_instruction=instruction,
            section_depth=depth,
        ) + json.dumps(data, indent=2)
        new_content = self.model.call_raw(prompt).strip()
        if not new_content:
            return
        self._insert_section(new_content, after)

    # ------------------------------------------------------------------
    # Action: remove a section entirely
    # ------------------------------------------------------------------

    def _remove_section(self, section):
        sec = self._find_section(section)
        if not sec:
            raise ValueError(f"Section not found: {section}")
        # Drop the section text and collapse the surrounding blank lines.
        self.qmd = (self.qmd[:sec["start"]] + self.qmd[sec["end"]:]).replace("\n\n\n\n", "\n\n")

    # ------------------------------------------------------------------
    # Action: reformat an existing section without changing facts
    # ------------------------------------------------------------------

    def _reformat_section(self, section, instruction):
        sec = self._find_section(section)
        if not sec:
            raise ValueError(f"Section not found: {section}")
        prompt = REFORMAT_SECTION_PROMPT.format(
            user_instruction=instruction,
        ) + sec["content"]
        new_content = self.model.call_raw(prompt).strip()
        if not new_content:
            return
        self._replace_section(sec, new_content)

    # ------------------------------------------------------------------
    # Action: create a new visualization and append it to a section
    # ------------------------------------------------------------------

    def _new_visualization(self, section, chart_type, title, rationale):
        sec = self._find_section(section)
        if not sec:
            raise ValueError(f"Section not found: {section}")

        # Build a data pool from real extracted stats so the LLM has only
        # concrete numbers to work with.
        data_points = self._collect_numeric_data_points()
        if len(data_points) < 2:
            # Planner should have refused already, but defensive guard.
            return

        prompt = NEW_VISUALIZATION_PROMPT.format(
            chart_type=chart_type,
            chart_title=title,
            rationale=rationale,
        ) + json.dumps(data_points, indent=2)
        block = self.model.call_raw(prompt).strip()
        if not block or "```{python}" not in block:
            return

        # Append the new block to the end of the target section.
        new_content = sec["content"].rstrip() + "\n\n" + block + "\n"
        self._replace_section(sec, new_content)

    # ------------------------------------------------------------------
    # Action: modify an existing visualization's styling
    # ------------------------------------------------------------------

    def _edit_visualization(self, chart_title, instruction):
        viz = self._find_visualization(chart_title)
        if not viz:
            raise ValueError(f"Visualization not found: {chart_title}")

        prompt = EDIT_VISUALIZATION_PROMPT.format(
            user_instruction=instruction,
        ) + viz["block"]
        new_block = self.model.call_raw(prompt).strip()
        if not new_block or "```{python}" not in new_block:
            return

        # Guard against the LLM dropping imports/setup — restore anything
        # from the original block that the new block is missing.
        new_block = self._repair_viz_block(new_block, viz["block"])

        # Splice the new block in place of the old one.
        self.qmd = self.qmd[:viz["start"]] + new_block + self.qmd[viz["end"]:]

    def _repair_viz_block(self, new_block, old_block):
        """Re-inject imports the LLM may have dropped when editing a viz block.

        Parses both blocks, finds import lines present in the old but missing
        from the new, and prepends them to the new block's body.
        """
        def _body(block):
            m = re.match(r"```\{python\}\n(.*?)```\s*$", block, re.DOTALL)
            return m.group(1) if m else None

        new_body = _body(new_block)
        old_body = _body(old_block)
        if new_body is None or old_body is None:
            return new_block

        import_pattern = re.compile(r"(?m)^\s*(?:import\s+\S+.*|from\s+\S+\s+import\s+.*)$")
        old_imports = import_pattern.findall(old_body)
        new_imports = set(import_pattern.findall(new_body))
        missing = [imp for imp in old_imports if imp not in new_imports]
        if not missing:
            return new_block

        repaired_body = "\n".join(missing) + "\n" + new_body.lstrip("\n")
        return "```{python}\n" + repaired_body + "```"

    # ------------------------------------------------------------------
    # Action: re-run synthesis with a new focus
    # ------------------------------------------------------------------

    def _reanalyze(self, focus, affected_sections=None):
        if not self.extractions:
            raise ValueError("Cannot reanalyze — extractions.json not available")

        prompt = REANALYZE_PROMPT.format(
            focus=focus,
            max_themes=self.config.get("max_themes", 4),
            max_takeaways=self.config.get("max_takeaways", 4),
        ) + json.dumps(self.extractions, indent=2)
        new_synthesis = self.model.call(prompt)

        # Replace the synthesis block in analysis.json; keep per_source/clusters
        # since re-running those would compound cost.
        self.analysis["synthesis"] = new_synthesis
        self._save_json("analysis.json", self.analysis)

        # Regenerate any sections the planner flagged as affected. If none were
        # flagged, only executive summary + themes are safe bets.
        to_regen = affected_sections or ["Executive Summary"]
        for title in to_regen:
            sec = self._find_section(title)
            if sec:
                self._rewrite_section(title, f"Refocus around: {focus}")

    # ------------------------------------------------------------------
    # Section parsing + editing helpers
    # ------------------------------------------------------------------

    def _split_sections(self):
        """Parse the .qmd into top-level (##) sections with byte offsets.

        Subsections (###) stay inside their parent — the editor operates at the
        ## level to match how reportMaker generates the document. The leading
        frontmatter + any intro text before the first ## is kept as a virtual
        "_frontmatter" entry so offsets still cover the full document.
        """
        sections = []
        # Match ## (but not ###) at start of a line.
        pattern = re.compile(r"(?m)^##(?!#)\s+(.+)$")
        matches = list(pattern.finditer(self.qmd))

        if not matches:
            return [{"title": "_frontmatter", "level": 0, "content": self.qmd, "start": 0, "end": len(self.qmd)}]

        # Frontmatter chunk before the first ##.
        if matches[0].start() > 0:
            sections.append({
                "title": "_frontmatter",
                "level": 0,
                "content": self.qmd[:matches[0].start()],
                "start": 0,
                "end": matches[0].start(),
            })

        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(self.qmd)
            sections.append({
                "title": m.group(1).strip(),
                "level": 2,
                "content": self.qmd[m.start():end],
                "start": m.start(),
                "end": end,
            })
        return sections

    def _find_section(self, title):
        """Locate a section by exact or case-insensitive title match."""
        for sec in self.sections:
            if sec["title"] == title:
                return sec
        low = title.strip().lower()
        for sec in self.sections:
            if sec["title"].lower() == low:
                return sec
        return None

    def _replace_section(self, sec, new_content):
        """Swap a section's text in the in-memory .qmd buffer."""
        if not new_content.endswith("\n"):
            new_content += "\n"
        self.qmd = self.qmd[:sec["start"]] + new_content + self.qmd[sec["end"]:]

    def _insert_section(self, new_content, after):
        """Insert a new section after the named section (or 'top'/'bottom')."""
        if not new_content.endswith("\n"):
            new_content += "\n"
        if after == "top":
            # After frontmatter if present, otherwise at the very start.
            fm = self._find_section("_frontmatter")
            insert_at = fm["end"] if fm else 0
        elif after == "bottom" or not after:
            insert_at = len(self.qmd)
        else:
            sec = self._find_section(after)
            insert_at = sec["end"] if sec else len(self.qmd)
        self.qmd = self.qmd[:insert_at] + "\n" + new_content + "\n" + self.qmd[insert_at:]

    # ------------------------------------------------------------------
    # Visualization parsing
    # ------------------------------------------------------------------

    def _extract_viz_blocks(self):
        """Find every ```{python} ... ``` block and pull its title from plt.title(...)."""
        blocks = []
        pattern = re.compile(r"```\{python\}\n(.*?)```", re.DOTALL)
        for m in pattern.finditer(self.qmd):
            body = m.group(1)
            title_match = re.search(r"plt\.title\(\s*['\"](.+?)['\"]", body)
            blocks.append({
                "title": title_match.group(1) if title_match else f"Chart @ {m.start()}",
                "block": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })
        return blocks

    def _find_visualization(self, title):
        """Locate a visualization block by exact or case-insensitive title match."""
        for v in self.visualizations:
            if v["title"] == title:
                return v
        low = title.strip().lower()
        for v in self.visualizations:
            if v["title"].lower() == low:
                return v
        return None

    def _collect_numeric_data_points(self):
        """Flatten every suggested_visuals data_point in the analysis into a
        single pool the LLM can draw from when building a new chart."""
        pool = []
        synthesis = self.analysis.get("synthesis", {}) or {}
        for viz in synthesis.get("visualizations", []) or []:
            for p in viz.get("data_points", []) or []:
                if p.get("value") not in (None, 0, ""):
                    pool.append({"label": p.get("label"), "value": p.get("value"), "from": viz.get("title")})
        for src in self.analysis.get("per_source", []) or []:
            for viz in src.get("suggested_visuals", []) or []:
                for p in viz.get("data_points", []) or []:
                    if p.get("value") not in (None, 0, ""):
                        pool.append({"label": p.get("label"), "value": p.get("value"), "from": viz.get("title")})
        return pool

    # ------------------------------------------------------------------
    # Section → analysis-data mapping
    # ------------------------------------------------------------------

    def _data_for_section(self, title):
        """Return the slice of analysis data that originally produced this section.

        Falls back to the whole synthesis if no section_map entry exists (older
        runs) — costs more tokens but still works.
        """
        entry = self.section_map.get(title)
        if not entry:
            return self.analysis.get("synthesis", {})

        # section_map entries can be either a plain JSON-pointer-ish path or
        # a dict with a "data" key holding the pre-resolved slice. Support both.
        if isinstance(entry, dict) and "data" in entry:
            return entry["data"]
        if isinstance(entry, dict) and "path" in entry:
            return self._resolve_path(entry["path"])
        if isinstance(entry, str):
            return self._resolve_path(entry)
        return entry

    def _resolve_path(self, path):
        """Resolve a dotted path like 'synthesis.themes[2]' against self.analysis."""
        obj = self.analysis
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\[\d+\]", path):
            if token.startswith("["):
                obj = obj[int(token[1:-1])]
            else:
                if isinstance(obj, dict):
                    obj = obj.get(token, {})
                else:
                    return {}
        return obj

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_json(self, name, default=None):
        path = os.path.join(self.run_dir, name)
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_json(self, name, data):
        path = os.path.join(self.run_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _load_qmd(self):
        with open(self.qmd_path, "r", encoding="utf-8") as f:
            return f.read()

    def _save_new_version(self):
        """Write current .qmd, archive prior to versions/report.vN.qmd, bump manifest."""
        versions_dir = os.path.join(self.run_dir, "versions")
        os.makedirs(versions_dir, exist_ok=True)

        existing = [f for f in os.listdir(versions_dir) if re.match(r"report\.v\d+\.qmd$", f)]
        next_n = max((int(re.search(r"v(\d+)", f).group(1)) for f in existing), default=-1) + 1

        # Archive the current on-disk .qmd BEFORE overwriting it, so vN holds
        # the state just before this edit.
        if os.path.exists(self.qmd_path):
            shutil.copy(self.qmd_path, os.path.join(versions_dir, f"report.v{next_n}.qmd"))

        with open(self.qmd_path, "w", encoding="utf-8") as f:
            f.write(self.qmd)

        # Track edit history in manifest.
        history = self.manifest.setdefault("edit_history", [])
        history.append({"version": next_n, "timestamp": datetime.now().isoformat()})
        self._save_json("manifest.json", self.manifest)
