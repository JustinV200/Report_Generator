"""CLI argument parsing and helper utilities for ReGen."""

import argparse
import os


def parse_args():
    """Parse command-line arguments and return the argparse Namespace."""
    parser = argparse.ArgumentParser(
        prog="regen",
        description="ReGen: AI-powered report generator"
    )
    # allow multiple sources as command-line arguments, or a .txt file with one source per line
    parser.add_argument(
        "sources", nargs="+",
        help="URLs, file paths, or .txt files containing one source per line"
    )
    # pick amount of detail — more detail = more tokens used = higher cost
    parser.add_argument(
        "-m", "--mode", choices=["brief", "standard", "detailed"],
        default="standard", help="Report detail level (default: standard)"
    )
    # output format, default to html
    parser.add_argument(
        "-o", "--output", choices=["html", "pdf", "docx"],
        default="html", help="Output format (default: html)"
    )
    # name of the output file without extension
    parser.add_argument(
        "--name", default="report",
        help="Output filename without extension (default: report)"
    )
    # LLM model to use, default to gpt-3.5-turbo, but allow any model supported by litellm
    parser.add_argument(
        "--model", default="gpt-3.5-turbo",
        help="LLM model name (default: gpt-3.5-turbo)"
    )
    # option to auto render or not
    parser.add_argument(
        "--render", action="store_true", default=False,
        help="Auto-render the .qmd with Quarto after generation"
    )
    # verbose mode to show detailed progress, including chunk-level extraction and reduce steps
    parser.add_argument(
        "-v", "--verbose", action="store_true", default=False,
        help="Show detailed progress (chunk-level extraction, reduce steps)"
    )
    # quiet mode to suppress all output except errors and final report path
    parser.add_argument(
        "-q", "--quiet", action="store_true", default=False,
        help="Suppress all output except errors and final report path"
    )
    # mode to export report to notion
    parser.add_argument(
        "-n", "--notion", action="store_true", default=False,
        help="Send the reports to a specified Notion Database"
    )
    return parser.parse_args()


def resolve_sources(raw_sources):
    """Expand .txt files into individual sources, one per line."""
    sources = []
    for s in raw_sources:
        if s.endswith(".txt") and os.path.isfile(s):
            with open(s, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        sources.append(line)
        else:
            sources.append(s)
    return sources


def log(msg, quiet=False):
    """Print a message unless quiet mode is on."""
    if not quiet:
        print(msg)
