"""Thin command entrypoint; research execution is intentionally not implemented."""
import argparse

from research_agent import __version__


def main(argv: list[str] | None = None) -> int:
    """Print help/version; argparse rejects unimplemented commands with exit 2."""
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description=(
            "Research Story Agent foundations. Research commands are not yet "
            "implemented; this release only provides help and version."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
