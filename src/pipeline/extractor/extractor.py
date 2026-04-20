"""Map-reduce extractor — extracts structured info from chunks, then consolidates via recursive reduce."""

import json
from models import Model
from prompts.extraction import EXTRACT_PROMPT, TABLE_PROMPT, REDUCE_PROMPT

#map: extract key info from each chunk individually
#reduce: if combined extractions exceed token limit, recursively split and reduce groups, then merge results up the chain
#final reduce consolidates everything into one extraction, this way LLM gets full document context since the compressed extractions now fit within the token limit
#and we can handle arbitrarily long documents without losing key info or context
class Extractor:
    """Extract and consolidate key information from document chunks using an LLM."""

    def __init__(self, model=None, max_tokens=2000, verbose=False):
        self.model = model or Model()
        self.max_tokens = max_tokens
        self.verbose = verbose


    def extract_chunk(self, chunk):
        """Send a single chunk to the LLM and return the structured extraction."""
        if chunk["chunk_type"] == "table":
            prompt = TABLE_PROMPT + json.dumps(chunk["content"])
        else:
            prompt = EXTRACT_PROMPT + chunk["content"]
        return self.model.call(prompt)
    

    def extract_all(self, chunks):
        """Run extract_chunk on every chunk and return the list of extractions."""
        extractions = []
        for i, chunk in enumerate(chunks, 1):
            if self.verbose:
                print(f"    Chunk {i}/{len(chunks)}...", end=" ", flush=True)
            result = self.extract_chunk(chunk)
            result["chunk_index"] = chunk["chunk_index"]
            extractions.append(result)
            if self.verbose:
                print("done")
        return extractions
    
    
    def _safe_call(self, prompt, retries=2):
        """Call model with retry on JSON parse errors."""
        for attempt in range(retries):
            try:
                return self.model.call(prompt)
            except json.JSONDecodeError:
                if attempt < retries - 1:
                    # Add instruction to keep response shorter
                    prompt = prompt + "\n\nIMPORTANT: Keep the JSON response concise. Limit each list to the top 10 most important items."
                else:
                    raise

    def reduce(self, extractions):
        """Recursively merge extractions until they fit in a single LLM call."""
        text = json.dumps(extractions, indent=2)

        # if it fits, do the final reduce in one call
        if len(text.split()) <= self.max_tokens:
            prompt = REDUCE_PROMPT + text
            return self._safe_call(prompt)

        # too big — batch reduce: group into chunks of batch_size, reduce each group, then recurse
        batch_size = 4
        batches = [extractions[i:i+batch_size] for i in range(0, len(extractions), batch_size)]
        reduced = []
        for i, batch in enumerate(batches, 1):
            if self.verbose:
                print(f"    Reduce batch {i}/{len(batches)} ({len(batch)} items)...", end=" ", flush=True)
            batch_text = json.dumps(batch, indent=2)
            if len(batch_text.split()) <= self.max_tokens:
                prompt = REDUCE_PROMPT + batch_text
                reduced.append(self._safe_call(prompt))
            else:
                # batch still too big, halve it
                #hey divide and conquer from csci311 mentioned
                mid = len(batch) // 2
                left = self.reduce(batch[:mid])
                right = self.reduce(batch[mid:])
                reduced.append(self.reduce([left, right]))
            if self.verbose:
                print("done")

        # if we're down to one result, we're done
        if len(reduced) == 1:
            return reduced[0]

        # otherwise recurse on the reduced results
        if self.verbose:
            print(f"    Final merge of {len(reduced)} batches...")
        return self.reduce(reduced)

    def run(self, chunks):
        """Execute the full map-reduce pipeline: extract all chunks, then reduce."""
        extractions = self.extract_all(chunks)  # map
        if self.verbose:
            print(f"  Reducing {len(extractions)} extractions...")
        consolidated = self.reduce(extractions)  # reduce
        return consolidated