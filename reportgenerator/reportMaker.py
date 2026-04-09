import json
import os
from datetime import date

REPORT_PROMPT = """You are a statistical report writing assistant. Given extracted data from a source document, generate a complete Quarto (.qmd) report.

The output MUST be valid Quarto markdown. Follow this structure, but fill in ALL sections with real content from the extracted data. NEVER use placeholder text like [2-3 paragraphs here] or [synthesize findings].

---
title: "[derive title from the data]"
author: "Report Generator"
date: "{date}"
format:
  {output_format}:
    theme: darkly
    toc: false
    number-sections: true
execute:
  echo: false
  warning: false
---

## Executive Summary

Write 2-3 real paragraphs summarizing the key findings from the extracted data.

## Key Entities

List all entities from the extracted data as bullet points.

## Key Findings

Present the extracted statistics and findings in whatever format best fits the data:
- Use a **markdown table** when there are many comparable metrics (same unit or category)
- Use **sub-sections** (### headers) to group findings by topic when data spans different domains
- Use **bullet points** for isolated facts that don't fit a table
- Always include the full date (with year) when referencing time-specific data
- Combine formats freely within this section as needed

## Claims & Evidence

For each claim, use this format:
### Claim N
**Statement:** the actual claim
**Evidence:** the actual supporting quote

## Analysis

```{{python}}
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Write REAL Python code that:
# 1. Creates DataFrames from the actual extracted statistics
# 2. Generates meaningful visualizations
# 3. Computes derived metrics where possible
# Do NOT write placeholder comments — write working code using the real data.
```

## Conclusions

Write a real concluding section that synthesizes the findings and provides actionable takeaways.
--RULES FOR WRITING THE REPORT( do not include these rules in the final report, they are just for you to follow):
CRITICAL FORMATTING RULES:
- Start with --- YAML frontmatter ---
- Use ## for section headers
- Use ```{{python}} for executable code blocks
- Use markdown tables for statistical data
- Do NOT use plain text headers like "Executive Summary:" — always use ## markdown headers
- Do NOT copy placeholder text from this template — generate real content for every section
- The Analysis code block MUST contain working Python code with real data, not comments or placeholders

VISUALIZATION RULES:
- Do NOT put unrelated metrics on the same chart
- Group related statistics together (e.g. variant percentages in one chart, weekly rates in another)
- Use plt.tight_layout() before plt.show() to prevent label cutoff
- Use horizontal bar charts (plt.barh) when labels are long
- Use separate ```{{python}} code blocks for separate visualizations
- Add a descriptive title and axis labels to every chart
- Use seaborn (sns) for cleaner styling when possible
- Set figure size with plt.figure(figsize=(10, 6)) for readability

Return ONLY the raw .qmd content. No wrapping, no explanation.

Extracted data:
"""

class reportMaker:
    def __init__(self, model = None, output_dir = "reports"):
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        self.model = model
        self.output_dir = output_dir

    def _fix_qmd(self, content):
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

    def generate(self, extraction, report_name="report", output_format="html"):
        prompt = REPORT_PROMPT.format(output_format=output_format, date=date.today().isoformat()) + json.dumps(extraction, indent=2)
        qmd_content = self._fix_qmd(self.model.call_raw(prompt))
        output_path = os.path.join(self.output_dir, f"{report_name}.qmd")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(qmd_content)
        
        return output_path