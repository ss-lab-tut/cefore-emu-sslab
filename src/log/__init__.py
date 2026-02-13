"""Log parsing and CSV summarization for Cefore experiments."""

from .filename import FilenameMeta, parse_filename
from .parser import (
    PARSERS,
    parse_cefgetfile,
    parse_cefpubfile,
    parse_cefputfile,
    parse_cefsubfile,
)
from .summarizer import collect_records, summarize, write_csv

__all__ = [
    "FilenameMeta",
    "parse_filename",
    "parse_cefputfile",
    "parse_cefgetfile",
    "parse_cefpubfile",
    "parse_cefsubfile",
    "PARSERS",
    "collect_records",
    "summarize",
    "write_csv",
    "plot_all",
]


def __getattr__(name: str):
    if name == "plot_all":
        from .plotter import plot_all

        return plot_all
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
