"""Tests for Soul digest functionality."""

import struct
import tempfile
from pathlib import Path

import pytest

from umann.utils.digest import Soul, extract_soul
from umann.utils.digest.soul import SoulPlugin


def test_soul_init_file():
    """Test Soul initialization with file path."""
    # Create a minimal JPG in memory for testing
    jpg_data = (
        b"\xff\xd8"  # SOI
        b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"  # APP0
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"  # SOS
        b"\x00\x00\x00"  # Some data
        b"\xff\xd9"  # EOI
    )

    s = Soul(content=jpg_data)
    assert s.content == jpg_data
    assert s.size == len(jpg_data)


def test_soul_init_validation():
    """Test that exactly one of file/content must be specified."""
    with pytest.raises(ValueError, match="Exactly one"):
        Soul()  # Neither specified

    with pytest.raises(ValueError, match="Exactly one"):
        Soul(file="test.jpg", content=b"data")  # Both specified


def test_soul_position_tracking():
    """Test position tracking functions."""
    s = Soul(content=b"0123456789")

    assert s.pos == 0
    assert s.pos_add(3) == 0
    assert s.pos == 3
    assert s.pos_set(7) == 3
    assert s.pos == 7


def test_soul_pos_read():
    """Test position-based reading."""
    s = Soul(content=b"ABCDEFGH")

    data = s.pos_read(3)
    assert data == b"ABC"
    assert s.pos == 3

    # With expected value
    data = s.pos_read(2, b"DE")
    assert data == b"DE"
    assert s.pos == 5

    # Expected mismatch
    with pytest.raises(Exception):  # SoulError
        s.pos_read(2, b"XX")


def test_soul_pos_find():
    """Test finding bytes in content."""
    s = Soul(content=b"Hello World")

    s.pos_set(0)
    assert s.pos_find(b"World") == 6

    s.pos_set(7)
    assert s.pos_find(b"Hello") is None  # Before current position


def test_soul_subcontent():
    """Test extracting substring."""
    s = Soul(content=b"0123456789")
    s.offset = 2
    s.length = 5

    assert s.subcontent() == b"23456"
    assert s.subcontent(offset=0, length=3) == b"012"


def test_jpg_plugin():
    """Test JPG soul extraction."""
    # Minimal JPG structure
    jpg_data = (
        b"\xff\xd8"  # SOI
        b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"  # APP0 marker + 16 byte payload
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"  # SOS (10 bytes)
        b"IMAGE_DATA"  # Image data (10 bytes)
        b"\xff\xd9"  # EOI (2 bytes)
    )

    s = Soul(content=jpg_data).compute()

    # Soul should start at SOS marker (FF DA)
    # SOI(2) + APP0 marker(2) + APP0 length(2) + APP0 data(14) = 20
    assert s.offset == 20
    # Soul should include from SOS to end: 10 + 10 + 2 = 22
    assert s.length == 22

    soul_bytes = s.result("soul")
    assert soul_bytes.startswith(b"\xff\xda")
    assert soul_bytes.endswith(b"\xff\xd9")


def test_mp3_plugin():
    """Test MP3 soul extraction."""
    # Minimal MP3 with ID3v2 header
    # Sync safe encoding for size 10: 0x00 0x00 0x00 0x0a -> already sync safe
    mp3_data = (
        b"ID3"  # ID3v2 identifier
        + b"\x04\x00"  # Version 2.4
        + b"\x00"  # Flags
        + b"\x00\x00\x00\x0a"  # Sync safe size (10 bytes) - correct
        + b"Y" * 10  # ID3 tag data (10 bytes)
        + b"\xff\xfb"  # MP3 frame sync
        + b"AUDIO_DATA"  # Audio data
    )

    s = Soul(content=mp3_data).compute()

    # Soul should start after ID3v2 header: 3 (ID3) + 3 (ver+flags) + 4 (size) + 10 (data) = 20
    assert s.offset == 20
    assert s.result("soul").startswith(b"\xff\xfb")


def test_png_plugin():
    """Test PNG soul extraction."""
    # Minimal PNG with IDAT chunk
    png_data = (
        b"\x89PNG\r\n\x1a\n"  # Signature
        # IHDR chunk
        + b"\x00\x00\x00\x0d"  # Length: 13
        + b"IHDR"  # Type
        + b"X" * 13  # Data
        + b"1234"  # CRC
        # IDAT chunk (soul)
        + b"\x00\x00\x00\x05"  # Length: 5
        + b"IDAT"  # Type
        + b"DATA!"  # Data
        + b"5678"  # CRC
        # IEND chunk
        + b"\x00\x00\x00\x00"  # Length: 0
        + b"IEND"  # Type
        + b"9abc"  # CRC
    )

    s = Soul(content=png_data).compute()

    # Soul should be the IDAT chunk (including header)
    idat_offset = 8 + (4 + 4 + 13 + 4)  # Signature + IHDR chunk
    assert s.offset == idat_offset

    soul_bytes = s.result("soul")
    assert b"IDAT" in soul_bytes
    assert b"DATA!" in soul_bytes


def test_mp4_plugin():
    """Test MP4 soul extraction."""

    # Build minimal MP4 structure with ftyp and mdat atoms
    movie_data = b"VIDEO_DATA" * 50
    mdat_size = 8 + len(movie_data)  # header (8) + data

    mp4_data = (
        # ftyp atom
        struct.pack(">I", 20)  # Size: 20 bytes
        + b"ftyp"  # Type
        + b"isom"  # Major brand
        + struct.pack(">I", 0)  # Minor version
        + b"isom"  # Compatible brand
        # mdat atom
        + struct.pack(">I", mdat_size)  # Size
        + b"mdat"  # Type
        + movie_data  # Movie data
    )

    s = Soul(content=mp4_data).compute()

    # Soul should start after mdat header: ftyp(20) + mdat header(8) = 28
    assert s.offset == 28
    assert s.length == len(movie_data)
    assert s.result("soul") == movie_data


def test_mov_plugin():
    """Test MOV/QuickTime soul extraction."""

    # Build minimal MOV structure with ftyp and mdat atoms
    movie_data = b"QT_MOVIE" * 40
    mdat_size = 8 + len(movie_data)  # header (8) + data

    mov_data = (
        # ftyp atom with 'qt  ' brand
        struct.pack(">I", 20)  # Size: 20 bytes
        + b"ftyp"  # Type
        + b"qt  "  # Major brand (QuickTime)
        + struct.pack(">I", 512)  # Minor version
        + b"qt  "  # Compatible brand
        # mdat atom
        + struct.pack(">I", mdat_size)  # Size
        + b"mdat"  # Type
        + movie_data  # Movie data
    )

    s = Soul(content=mov_data).compute()

    # Soul should start after mdat header: ftyp(20) + mdat header(8) = 28
    assert s.offset == 28
    assert s.length == len(movie_data)
    assert s.result("soul") == movie_data


def test_avi_plugin():
    """Test AVI soul extraction."""

    # Build minimal AVI structure
    movi_data = b"VIDEO" * 100
    movi_size = len(movi_data) + 4  # +4 for "movi" type

    # Total RIFF size = everything after the RIFF header (8 bytes)
    riff_data_size = 4 + 8 + movi_size  # "AVI " + LIST header + movi chunk

    avi_data = (
        b"RIFF"
        + struct.pack("<I", riff_data_size)  # Correct total size
        + b"AVI "
        + b"LIST"
        + struct.pack("<I", movi_size)
        + b"movi"
        + movi_data
    )

    s = Soul(content=avi_data).compute()

    # Soul starts at the movi subtype and excludes the LIST header.
    assert s.offset == 20
    assert s.length == movi_size
    assert s.result("soul") == b"movi" + movi_data


def test_soul_result_fields():
    """Test result() method with various fields."""
    jpg_data = b"\xff\xd8" b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" b"DATA" b"\xff\xd9"

    s = Soul(content=jpg_data).compute()

    # Single field
    assert isinstance(s.result("offset"), int)
    assert isinstance(s.result("length"), int)
    assert isinstance(s.result("soul"), bytes)
    assert isinstance(s.result("md5_soul"), str)
    assert len(s.result("md5_soul")) == 32  # MD5 hex length

    # Multiple fields
    offset, length = s.result("offset", "length")
    assert isinstance(offset, int)
    assert isinstance(length, int)

    # Default (md5_soul)
    assert s.result() == s.result("md5_soul")


def test_soul_convenience_function():
    """Test the soul() convenience function."""
    jpg_data = b"\xff\xd8" b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" b"DATA" b"\xff\xd9"

    # Create temp file

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(jpg_data)
        temp_path = f.name

    try:
        # Test convenience function
        md5_hash = extract_soul(temp_path)
        assert isinstance(md5_hash, str)
        assert len(md5_hash) == 32

        # Test with multiple fields
        offset, length = extract_soul(temp_path, "offset", "length")
        assert isinstance(offset, int)
        assert isinstance(length, int)
    finally:
        Path(temp_path).unlink()


def test_unknown_format_is_soulless():
    """Test fallback handling when no format-specific plugin matches."""

    unknown_data = b"UNKNOWN_FORMAT_12345"

    s = Soul(content=unknown_data).compute()

    assert s.soulless is True
    assert s.offset is None
    assert s.length is None
    assert s.result("soul") is None
    assert s.result("md5_soul") is None


def test_plugin_supported_extensions_is_class_attribute():
    """Plugins should expose supported extensions as a regular class attribute."""

    class DummyPlugin(SoulPlugin):
        """Dummy plugin for testing."""

        @classmethod
        def can_handle_content(cls, soul):
            return True

        def handle(self) -> None:
            self.soul.offset = 0
            self.soul.length = 0

    assert DummyPlugin.SUPPORTED_EXTENSIONS == set()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
