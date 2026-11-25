"""Low-level text helpers shared by the parser, presets and auto-mapping. No I/O."""

import csv
import io
import unicodedata
from collections.abc import Iterator

HEADER_SEARCH_LINES = 30
"""How many records at the top of a file are searched for the header row."""

_BOM = "﻿"
_TRANSLITERATION = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def decode_bytes(data: bytes, encoding: str) -> str:
    """Decode a file and strip a leading BOM.

    ``auto`` tries UTF-8 first (with BOM) and falls back to cp1252, then to ISO-8859-1.
    An explicit encoding that cannot decode the file raises ``ValueError``.
    """
    if encoding == "auto":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1252")
            except UnicodeDecodeError:
                text = data.decode("iso-8859-1")
    else:
        # utf-8 files may carry a BOM, so treat both spellings alike.
        codec = "utf-8-sig" if encoding == "utf-8" else encoding
        try:
            text = data.decode(codec)
        except UnicodeDecodeError:
            raise ValueError(f"file is not valid {encoding}") from None
    return text.removeprefix(_BOM)


def normalize(name: str) -> str:
    """Reduce a header to a comparable key.

    Case-insensitive, ignores punctuation, whitespace, ``(€)``, ``(EUR)`` and ``*``, and folds
    umlauts to their transliteration so ``Währung`` equals ``Waehrung``.
    """
    text = unicodedata.normalize("NFC", name).casefold().replace(_BOM, "")
    text = text.replace("(€)", "").replace("(eur)", "").replace("*", "")
    text = text.translate(_TRANSLITERATION)
    return "".join(ch for ch in text if ch.isalnum())


def dedupe_headers(cells: list[str]) -> list[str]:
    """Strip header cells and rename repeats (``Währung``, ``Währung_2``, ...)."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for cell in cells:
        name = cell.strip()
        count = seen.get(name, 0) + 1
        seen[name] = count
        result.append(name if count == 1 else f"{name}_{count}")
    return result


def read_records(text: str, delimiter: str, quotechar: str) -> Iterator[tuple[int, list[str] | None]]:
    """Yield ``(line_no, cells)`` per CSV record; ``cells`` is ``None`` for a malformed record.

    ``line_no`` is the 1-based physical line on which the record ends.
    """
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar=quotechar)
    while True:
        try:
            cells = next(reader)
        except StopIteration:
            return
        except csv.Error:
            yield reader.line_num, None
            continue
        yield reader.line_num, cells
