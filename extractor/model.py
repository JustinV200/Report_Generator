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

TABLE_PROMPT = """You are a data extraction assistant. Analyze this table data and extract key statistics and insights.

Return ONLY valid JSON in the same format as above.

Table data:
"""

REDUCE_PROMPT = """You are given extractions from multiple chunks of the same document.
Consolidate into a single extraction:
- Deduplicate entities
- Merge statistics (flag contradictions)
- Keep only well-supported claims
- Write one overall document summary

Return ONLY valid JSON in the same structured format.

Chunk extractions:
"""

import json
import os
from litellm import completion

class Model:
    def __init__(self, model_name="gpt-3.5-turbo"):
        self.model_name = model_name
        self.extract_prompt = EXTRACT_PROMPT
        self.table_prompt = TABLE_PROMPT
        self.reduce_prompt = REDUCE_PROMPT

    def call(self, prompt):
        response = completion(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    
    def call_raw(self, prompt):
        response = completion(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content