"""CLI argument parsing and helper utilities for ReGen."""

import argparse
import os
import sys


def parse_args():
    """Parse command-line arguments and return the argparse Namespace.

    Two entry points:
      - default (generate):  regen <sources...> [options]   — runs the full pipeline
      - edit subcommand:     regen edit <run_name> [request] [options] — opens the editor

    The generate flow stays backward-compatible: if the first positional arg is
    not a known subcommand, it is treated as a source and the old single-command
    behavior is used.
    """
    # Peek at argv to decide whether to route to a subcommand. argparse makes
    # optional subparsers awkward when the default command takes positional
    # args, so we dispatch manually.
    subcommands = {"edit"}
    argv = sys.argv[1:]
    if argv and argv[0] in subcommands:
        return _parse_subcommand(argv[0], argv[1:])
    return _parse_generate(argv)


VERSION = "0.1.0"


def _parse_generate(argv):
    """Parser for the default generate pipeline."""
    parser = argparse.ArgumentParser(
        prog="regen",
        description="ReGen: AI-powered report generator",
        epilog="Subcommands:\n  edit <run_name>  Edit an existing report interactively\n\nRun 'python ReGen.py edit --help' for edit subcommand options.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(command="generate")
    parser.add_argument(
        "-v", "--version", action="version", version=f"ReGen {VERSION}"
    )
    parser.add_argument(
        "sources", nargs="+",
        help="URLs, file paths, or .txt files containing one source per line"
    )
    parser.add_argument(
        "-m", "--mode", choices=["brief", "standard", "detailed"],
        default="standard", help="Report detail level (default: standard)"
    )
    parser.add_argument(
        "-o", "--output", choices=["html", "pdf", "docx"],
        default="html", help="Output format (default: html)"
    )
    parser.add_argument(
        "--name", default="report",
        help="Output report name / run directory (default: report)"
    )
    parser.add_argument(
        "--model", default="gpt-3.5-turbo",
        help="LLM model name (default: gpt-3.5-turbo)"
    )
    parser.add_argument(
        "--render", action="store_true", default=False,
        help="Auto-render the .qmd with Quarto after generation"
    )
    parser.add_argument(
        "--verbose", action="store_true", default=True,
        help="Show detailed progress (chunk-level extraction, reduce steps)"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", default=False,
        help="Suppress all output except errors and final report path"
    )
    parser.add_argument(
        "-n", "--notion", action="store_true", default=False,
        help="Push report to Notion (requires NOTION_TOKEN env var)"
    )
    return parser.parse_args(argv)


def _parse_subcommand(name, argv):
    """Parser for the `edit` subcommand — interactive or single-shot edits."""
    if name == "edit":
        parser = argparse.ArgumentParser(
            prog="regen edit",
            description="Edit an existing report via LLM agent",
            epilog="Examples:\n  python ReGen.py edit report\n  python ReGen.py edit report \"make the executive summary shorter\"\n\nrun_name is the folder name under reports/ (e.g. 'report' for reports/report/).",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.set_defaults(command="edit")
        parser.add_argument("run_name", help="Name of the report run (directory under reports/)")
        parser.add_argument("request", nargs="?", default=None,
                            help="Edit request. If omitted, enters interactive mode")
        parser.add_argument("-i", "--interactive", action="store_true", default=False,
                            help="Enter an interactive REPL-style edit session")
        parser.add_argument("-m", "--mode", choices=["brief", "standard", "detailed"],
                            default="standard", help="Depth settings for generated sections (default: standard)")
        parser.add_argument("--model", default="gpt-3.5-turbo", help="LLM model name (default: gpt-3.5-turbo)")
        parser.add_argument("--render", action="store_true", default=False,
                            help="Re-render the .qmd with Quarto after edits")
        parser.add_argument("-o", "--output", choices=["html", "pdf", "docx"],
                            default="html", help="Output format for --render (default: html)")
        parser.add_argument("--verbose", action="store_true", default=False,
                            help="Show detailed progress")
        parser.add_argument("-q", "--quiet", action="store_true", default=False,
                            help="Suppress all output except errors and final report path")
        parser.add_argument("-n", "--notion", action="store_true", default=False,
                            help="Push updated report to Notion (requires NOTION_TOKEN env var)")
        return parser.parse_args(argv)
    raise ValueError(f"Unknown subcommand: {name}")


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
