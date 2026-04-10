<p align="center">
  <img src="assets/banner.svg" alt="ReGen" width="800"/>
</p>

<p align="center">
  <em>Ingest documents. Extract intelligence. Generate reports.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/LLM-GPT--3.5--turbo-412991?style=flat-square&logo=openai&logoColor=white" alt="LLM"/>
  <img src="https://img.shields.io/badge/render-Quarto-75AADB?style=flat-square" alt="Quarto"/>
</p>

---

An automated pipeline that ingests documents or web pages, extracts structured data using LLMs, analyzes cross-source patterns, and generates polished reports rendered with [Quarto](https://quarto.org).

## How It Works

```
Sources (URLs/files)
  → Parse → Chunk
  → LLM Extract (map-reduce)
  → LLM Analyze (per-source + clustering + cross-source synthesis)
  → LLM Report Writer (section-by-section)
  → Quarto .qmd → HTML/PDF/DOCX
```

1. **Input Ingestion** — Detects whether each source is a URL or local file, downloads if needed, identifies the file type, and dispatches to the appropriate parser.
2. **Chunking** — Splits parsed text into overlapping chunks sized for LLM context windows. Tables are kept as separate chunks. Handles paragraph-less documents with newline/word-split fallbacks.
3. **Extraction (Map-Reduce)** — Each chunk is sent to an LLM for structured data extraction (entities, statistics, claims). Results are batch-reduced into a single JSON extraction per source.
4. **Analysis & Synthesis** — Per-source deep analysis, source clustering by topic similarity, and cross-source synthesis that identifies themes, connections, contradictions, and key takeaways.
5. **Report Generation** — Section-by-section LLM calls build a complete Quarto `.qmd` with narrative prose, charts (matplotlib/seaborn), and data-driven visualizations.
6. **Rendering** — Quarto compiles the `.qmd` into a self-contained HTML file (or PDF/DOCX). Embedded resources — no extra folders needed.

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

1. Open `Main.py` and set your sources and mode:

```python
sources = [
    "https://example.com/article",
    "https://example.com/report",
    "data/study.pdf",
]
mode = "standard"  # "brief", "standard", or "detailed"
```

| Mode | Description |
|---|---|
| `brief` | Quick summary, minimal sections, single-call generation |
| `standard` | Themes, cross-source findings, clusters — section-by-section |
| `detailed` | Everything in standard + per-source deep-dives, more themes/takeaways |

2. Run the pipeline:

```bash
python Main.py
```

3. The generated `.qmd` file is saved to `reports/`. Render it with:

```bash
quarto render reports/report.qmd
```

The rendered HTML is fully self-contained — open it on any machine, no extra files needed.

## Project Structure

```
report_generator/
├── Main.py                          # Pipeline orchestrator + mode config
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
├── analyzer/
│   └── analyzer.py                  # Per-source analysis, clustering, synthesis
├── reportgenerator/
│   └── reportMaker.py               # Section-by-section Quarto .qmd generation
├── reports/                         # Generated reports output directory
├── assets/                          # README banner and other assets
├── requirements.txt
└── .env                             # API keys (not committed)
```

## Roadmap
- [x] Multi-source support — accept a list of URLs/files, extract each independently, synthesize across all
- [x] Report modes — `brief`, `standard`, `detailed` with scaling themes, takeaways, and section depth
- [x] Analyzer layer — per-source analysis, topic clustering, cross-source synthesis
- [x] Section-by-section generation — avoids LLM output token limits on longer reports
- [x] Self-contained HTML — `embed-resources` for portable single-file reports
- [ ] **Research mode** — given a topic, auto-search the web for relevant sources and feed the best ones into the pipeline
- [ ] **Local fine-tuned models** — swap cloud LLMs for locally-hosted models for cost, privacy, and offline use
- [ ] **CLI interface** — command-line arguments for sources, mode, output format
