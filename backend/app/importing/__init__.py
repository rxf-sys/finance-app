"""Pure CSV parsing for bank statement imports (no database, no I/O)."""

from app.importing.automap import SuggestedFormat, suggest_format
from app.importing.config import ColumnMap, CsvFormat
from app.importing.parser import (
    MAX_ROWS,
    ParsedRow,
    ParseResult,
    RowError,
    detect_preset,
    parse,
    parse_amount_cents,
)
from app.importing.presets import PRESETS, Preset, get_preset

__all__ = [
    "MAX_ROWS",
    "PRESETS",
    "ColumnMap",
    "CsvFormat",
    "ParseResult",
    "ParsedRow",
    "Preset",
    "RowError",
    "SuggestedFormat",
    "detect_preset",
    "get_preset",
    "parse",
    "parse_amount_cents",
    "suggest_format",
]
