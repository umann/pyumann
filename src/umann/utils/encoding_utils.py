"""Module for encoding utilities."""

import re

MOJIBAKE1_RE = re.compile(r"[ÃÂÅ]")
MOJIBAKE2_RE = re.compile(MOJIBAKE1_RE.pattern + r"[\x80-\xbf]")


def fix_str_encoding(text: str) -> str:
    """Detect and fix IPTC text encoding issues.

    ExifTool returns IPTC as Latin1 by default. This function detects if the text
    was actually UTF-8 and decodes it correctly.

    Args:
        text: String that may be incorrectly decoded

    Returns:
        Properly decoded string

    Raises:
        ValueError: If text contains suspicious characters indicating encoding issues
    """
    if not isinstance(text, str) or not text:
        return text

    # Red flags: characters suggesting UTF-8 misread as Latin1/Windows-1252/Latin2
    # Ã (not before o/O), Å, Â are common UTF-8 → Latin1 misread artifacts
    if not MOJIBAKE1_RE.search(text):
        return text  # No suspicious characters, assume correct

    # Try different encodings that ExifTool might have used to decode UTF-8
    for source_encoding in ["latin2", "latin1", "cp1252"]:
        try:
            # Assume: UTF-8 bytes were incorrectly decoded as source_encoding
            fixed = text.encode(source_encoding).decode("utf-8")
            # Verify fix worked: no more suspicious characters
            if not MOJIBAKE1_RE.search(fixed):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue

    if MOJIBAKE2_RE.search(text):
        raise ValueError(f"Could not fix encoding for: {text!r}")

    return text  # Return original if no fix found but not suspicious
