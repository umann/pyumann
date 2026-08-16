"""
Module for encoding utilities.
It addresses the issue of mojibake in EXIF metadata by trying to detect and repair common encoding mistakes.
Mojibake means that UTF-8 bytes were misinterpreted as single-byte encodings like Latin-1, Latin-2, or CP1252,
resulting in garbled text.
NB it's ported to mgvwr/src/encoding_utils.cpp. Both Python and C++ versions were created by Copilot.
"""

import re
import typing as t

MOJIBAKE1_RE = re.compile(r"[ÃÂÅ]")
MOJIBAKE2_RE = re.compile(MOJIBAKE1_RE.pattern + r"[\x80-\xbf]")


def _fix_string_encoding(data: str, force_language: str | None) -> str:
    """Fix mojibake artifacts in a string using common source encodings."""
    if not MOJIBAKE1_RE.search(data):
        return data

    for source_encoding in ["latin2", "latin1", "cp1252"]:
        try:
            fixed = data.encode(source_encoding).decode("utf-8")
            if not MOJIBAKE1_RE.search(fixed):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue

    if MOJIBAKE2_RE.search(data):
        raise ValueError(f"Could not fix encoding for: {data!r}")
    if force_language == "hu":
        data = data.translate(str.maketrans("õÕûÛ", "őŐűŰ"))
    return data


def fix_str_encoding(
    data: str | list[str] | tuple[str] | set[str] | dict[str, t.Any], force_language: str | None = None
) -> str:
    """Detect and fix IPTC text encoding issues.

        ExifTool returns IPTC as Latin1 by default. This function detects if the text
        was actually UTF-8 and decodes it correctly.

        Args:
            text: String or sequence of strings that may be incorrectly decoded
            force_charset: If set to "ISO-8859-2", it will also fix specific character mappings,
                           currently Hungarian ones only.

        Returns:
            Properly decoded string
    ISO-8859-2)

        Raises:
            ValueError: If text contains suspicious characters indicating encoding issues
    """
    result = data
    if isinstance(data, (bool, type(None))):
        result = data
    elif isinstance(data, (int, float)):
        result = str(data)
    else:
        typ = type(data)
        if isinstance(data, (list, tuple, set)):
            result = typ(fix_str_encoding(t, force_language=force_language) for t in data)
        elif isinstance(data, dict):
            result = {k: fix_str_encoding(v, force_language=force_language) for k, v in data.items()}
        elif isinstance(data, str):
            result = _fix_string_encoding(data, force_language)
        else:
            raise TypeError(f"Expected str or list/tuple/set of str, got {typ=} {data=}") from None
    return result
