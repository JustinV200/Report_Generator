import json
import os

REPORT_PROMPT = """You are a statistical report writing assistant. Given extracted data from a source document, generate a complete Quarto (.qmd) report.

Requirements:
1. Start with YAML frontmatter:
---
title: "[derive title from the data]"
author: "Report Generator"
date: today
format: {output_format}
execute:
  echo: false
  warning: false
---

2. Structure the report with these sections:
   - Executive Summary: 2-3 paragraph overview of key findings
   - Key Entities: who/what organizations, people, or systems are involved
   - Statistical Findings: present all statistics found, with context and interpretation
   - Claims & Evidence: major claims from the source, with supporting evidence
   - Analysis: Python code blocks that compute summary statistics, create visualizations, or cross-reference data points
   - Conclusions: synthesize findings into actionable takeaways

3. For the Analysis section, use executable Python code blocks with ```{{python}} that:
   - Create pandas DataFrames from the extracted statistics
   - Generate plots with matplotlib or seaborn where appropriate
   - Compute derived metrics (percentages, comparisons, trends)
   - Display formatted tables

4. Use proper markdown formatting: headers, bullet points, bold for emphasis
5. Reference specific numbers and quotes from the extracted data
6. Flag any contradictions or gaps in the data

Return ONLY the raw .qmd file content. No wrapping, no explanation, no markdown code fences around the output.

Extracted data:
"""


class reportMaker:
    def __init__(self, model = None, output_dir = "reports"):
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        self.model = model
        self.output_dir = output_dir

    def generate(self, extraction, report_name="report", output_format="html"):
        prompt = REPORT_PROMPT.format(output_format=output_format) + json.dumps(extraction, indent=2)
        qmd_content = self.model.call_raw(prompt)  # need raw text, not JSON
        
        output_path = os.path.join(self.output_dir, f"{report_name}.qmd")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(qmd_content)
        
        return output_path