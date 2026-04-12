"""Main pipeline orchestration — input parsing → extraction → analysis → report generation → optional render."""

import subprocess
import sys

from input_processing import Reader, chunker
from models import Model
from extractor import Extractor
from analyzer import Analyzer
from reportgenerator import reportMaker

from core.config import get_mode_config
from core.cli import parse_args, resolve_sources, log


def main():
    """Run the full ReGen pipeline from CLI arguments to final report."""
    args = parse_args()

    if args.verbose and args.quiet:
        print("Error: --verbose and --quiet cannot be used together.", file=sys.stderr)
        sys.exit(1)

    sources = resolve_sources(args.sources)
    # error handling for no sources
    if not sources:
        print("Error: No sources provided.", file=sys.stderr)
        sys.exit(1)

    mode = args.mode
    log(f"Running in {mode} mode with {len(sources)} sources...", args.quiet)
    # get model and config based on mode and number of sources
    model = Model(model_name=args.model)
    config = get_mode_config(mode, len(sources))

    # For each source, read, parse, chunk, and extract
    extractions = []
    log("Extracting information from sources...", args.quiet)
    for i, source in enumerate(sources, 1):
        log(f"\n[{i}/{len(sources)}] Processing: {source[:80]}...", args.quiet)
        try:
            # read the source and get the file type, send to relevent parser
            reader = Reader(source)
            # parse the data
            parsed = reader.parse()
            # chunk the data into smaller pieces for extraction
            chunks = chunker(parsed)
        # error handling
        except Exception as e:
            log(f"  Failed to read source: {e}", args.quiet)
            continue
        if not chunks:
            log(f"  No content extracted, skipping", args.quiet)
            continue
        log(f"  → {len(chunks)} chunks to extract", args.quiet)
        # extract key information from the chunks using the model, recursively make
        # smaller and smaller until below max token size, then reduce all the chunks
        # into one final extraction for this source
        extractor = Extractor(model=model, verbose=args.verbose)
        result = extractor.run(chunks)
        # Skip empty/unknown extractions
        if not result or (not result.get("entities") and not result.get("statistics") and not result.get("claims")):
            log(f"  No meaningful data extracted, skipping", args.quiet)
            continue
        # Tag with real source identifier so analyzer uses it instead of inventing names
        result["_source_id"] = source
        extractions.append(result)
        log(f"  ✓ Source {i} done", args.quiet)

    if not extractions:
        print("No usable data from any source. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Analyze each source's extraction, break into clusters if needed, if standard/detailed
    # mode synthesize insights from medium/high relevance clusters, and identify key themes
    # and takeaways across sources, then synthesize into overall insights and themes
    log("Analyzing and synthesizing extracted information...", args.quiet)
    analyzer = Analyzer(model=model, config=config)
    analysis = analyzer.run(extractions)

    # Collect raw stats from all extractions so reportMaker can validate visualizations
    analysis["_raw_stats"] = []
    for ext in extractions:
        analysis["_raw_stats"].extend(ext.get("statistics", []))

    # Use the analysis to generate a report, save to disk, and optionally render with Quarto
    log("Generating report...", args.quiet)
    report = reportMaker(model=model, config=config)
    report_path = report.generate(analysis, report_name=args.name, output_format=args.output)
    log(f"Report saved to: {report_path}", args.quiet)

    # Render with Quarto if requested
    if args.render:
        log("Rendering with Quarto...", args.quiet)
        result = subprocess.run(
            ["quarto", "render", report_path],
            capture_output=args.quiet,
        )
        if result.returncode == 0:
            rendered = report_path.replace(".qmd", f".{args.output}")
            print(rendered)
        else:
            print(f"Quarto render failed (exit code {result.returncode})", file=sys.stderr)
            if args.quiet and result.stderr:
                print(result.stderr.decode(), file=sys.stderr)
            sys.exit(1)
    elif not args.quiet:
        print(f"\nRun 'quarto render {report_path}' to render the report.")
