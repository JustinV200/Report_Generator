# Report Generator

An automated pipeline that ingests documents or web pages, extracts structured data using LLMs, and generates polished statistical reports rendered with [Quarto](https://quarto.org).

## How It Works

```
Source (URL or file) → Parse → Chunk → LLM Extract (map-reduce) → LLM Report Writer → Quarto .qmd → HTML/PDF/DOCX
```

1. **Input Ingestion** — Detects whether the source is a URL or local file, downloads if needed, identifies the file type, and dispatches to the appropriate parser.
2. **Chunking** — Splits parsed text into overlapping chunks sized for LLM context windows. Tables are kept as separate chunks.
3. **Extraction (Map-Reduce)** — Each chunk is sent to an LLM for structured data extraction (entities, statistics, claims). Results are recursively consolidated into a single JSON extraction.
4. **Report Generation** — A second LLM call transforms the extraction JSON into a complete Quarto `.qmd` report with narrative sections, tables, and executable Python visualizations.
5. **Rendering** — Quarto compiles the `.qmd` into HTML (or PDF/DOCX).

## Supported Input Formats

| Format | Parser |
|---|---|
| Web pages (URL) | trafilatura |
| PDF | PyMuPDF + pdfplumber |
| Word (.docx) | python-docx |
| Excel (.xlsx) | pandas + openpyxl |
| CSV | pandas |
| Plain text | built-in |

## Setup

**Prerequisites:**
- Python 3.10+
- [Quarto](https://quarto.org/docs/get-started/) installed and on PATH
- An OpenAI API key (or any provider supported by [litellm](https://docs.litellm.ai/))

**Install dependencies:**

```bash
pip install -r requirements.txt
```

**Configure environment:**

Create a `.env` file in the project root:

```
OPENAI_API_KEY=your-key-here
```

If Quarto picks up the wrong Python interpreter, set:

```powershell
$env:QUARTO_PYTHON = "C:\path\to\python.exe"
```

## Usage

1. Open `Main.py` and set the `source` variable to a URL or local file path:

```python
source = "https://example.com/article"   # URL
source = "data/report.pdf"               # local file
```

2. Run the pipeline:

```bash
python Main.py
```

3. The generated `.qmd` file is saved to `reports/`. Render it with:

```bash
quarto render reports/report.qmd
```

The rendered HTML will appear in the same directory.

## Project Structure

```
report_generator/
├── Main.py                          # Pipeline entry point
├── input_processing/
│   ├── reader.py                    # Source detection, download, MIME routing
│   ├── chunker.py                   # Paragraph-based chunking with overlap
│   └── parsers/
│       ├── text_parser.py
│       ├── csv_parser.py
│       ├── docx_parser.py
│       ├── pdf_parser.py
│       ├── excelParser.py
│       └── web_parser.py
├── extractor/
│   ├── model.py                     # LLM wrapper (litellm, provider-agnostic)
│   └── extractor.py                 # Map-reduce extraction pipeline
├── reportgenerator/
│   └── reportMaker.py               # Quarto .qmd generation from extraction JSON
├── reports/                         # Generated reports output directory
├── requirements.txt
└── .env                             # API keys (not committed)
```

## Roadmap
- [ ] **Cleaner accurate reports** - cleanup reports, better prompts for the llm to follow in report making
- [ ] **Multiple source support** — Accept a list of URLs/files, parse and chunk each, merge all chunks before extraction to produce a single unified report from multiple sources.
- [ ] **Report size tiers** — `brief`, `standard`, and `detailed` modes that control how much content the report writer generates (summary-only vs. full analysis with deep-dives).
- [ ] **Research mode** — Given a topic, automatically search the web for relevant sources, rank them, and feed the best ones into the pipeline. Turns the tool into an autonomous research assistant.
- [ ] **Local fine-tuned models** — Swap out cloud LLMs for locally-hosted models fine-tuned on domain-specific extraction and report writing tasks. Reduces cost, improves privacy, and allows offline use.