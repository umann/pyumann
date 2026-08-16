"""Helpers to resolve Picasa contact hex IDs to nicknames and back."""

from __future__ import annotations

import re
import sys
import typing as t
import xml.etree.ElementTree as ET
from pathlib import Path

from munch import Munch

from umann.config import get_config

__all__ = ["nick_of_hex", "hex_of_nick", "faces_to_exif", "rect64_to_xywh01", "xywh01_to_rect64"]

# Module-level caches populated on first access
GLOBAL: Munch[str, t.Any] = Munch(
    nick_to_hexes=dict[str, list[str]](),
    hex_to_details=dict[str, dict[str, t.Any]](),  # contact_hex -> {name, emails, ...}
    loaded=False,
)


class PicasaIniError(Exception):
    """Raised when a .picasa.ini file is malformed or inconsistent."""


def _contacts_path() -> Path:
    contacts_xml = Path(get_config("picasa.contacts_xml"))
    if not contacts_xml.exists():
        raise FileNotFoundError(f"contacts_xml not found at {contacts_xml}")
    return contacts_xml


# pylint: disable=too-many-locals
def _load_contacts() -> None:
    if GLOBAL.loaded:
        return

    contacts_xml = _contacts_path()
    tree = ET.parse(contacts_xml)
    root = tree.getroot()

    nick_to_hex: dict[str, list[str]] = {}
    contact_details: dict[str, dict[str, t.Any]] = {}
    unique_required = bool(get_config("picasa.contact_nick_unique", default=True))
    hex_re = re.compile(r"^[0-9a-fA-F]{1,16}$")

    for contact in root.iter("contact"):
        contact_hex = contact.attrib.get("id") or contact.attrib.get("contactid")
        nick_raw = contact.attrib.get("name") or contact.attrib.get("display") or contact.attrib.get("nick")

        if not contact_hex or not hex_re.match(contact_hex):
            continue
        contact_hex = contact_hex.lower()

        if not nick_raw:
            continue
        nick = nick_raw.strip()
        if not nick:
            continue

        # Collect emails for face type detection.
        # Picasa stores addresses as attributes (email0, email1, ...).
        emails = []
        for key, value in sorted(contact.attrib.items()):
            if key.startswith("email") and value:
                email = value.strip()
                if email:
                    emails.append(email)

        # Record nick -> hex list
        bucket = nick_to_hex.setdefault(nick, [])
        if contact_hex not in bucket:
            bucket.append(contact_hex)

        # Store full contact details
        contact_details[contact_hex] = {"name": nick, "emails": emails}

    if unique_required:
        dup_nicks = [(nick, hexes) for nick, hexes in nick_to_hex.items() if len(hexes) > 1]
        if dup_nicks:
            raise ValueError(
                "contact_nick_unique is True but duplicate nicknames were found: "
                + ", ".join(map(str, sorted(dup_nicks)))
            )

    GLOBAL.nick_to_hexes = nick_to_hex
    GLOBAL.hex_to_details = contact_details
    GLOBAL.loaded = True


def get_contact_details(nick: str | None = None, hexa: str | None = None) -> dict[str, t.Any] | None:  # noqa
    assert (nick is None) != (hexa is None), "Exactly one of nick or hex must be provided"
    _load_contacts()
    if hexa is None:
        hexa = hex_of_nick(nick)
        if isinstance(hexa, tuple):
            raise ValueError(f"Multiple hexes found for nick '{nick}': {hexa}")
    return GLOBAL.hex_to_details.get(hexa)


def all_names() -> list[str]:  # noqa
    _load_contacts()
    return list(GLOBAL.nick_to_hexes)


def nick_of_hex(contact_hex: str | None) -> str | None:
    """Return nickname for a contact hex (lowercased), or None if missing."""
    if contact_hex is None:
        return None
    _load_contacts()
    contact = GLOBAL.hex_to_details.get(contact_hex.lower())
    return contact.get("name") if contact else None


def hex_of_nick(nick: str | None) -> str | tuple[str, ...] | None:
    """Return hex for a nickname. If multiple exist, return a tuple; None if not found."""
    if nick is None:
        return None
    _load_contacts()
    hexes = GLOBAL.nick_to_hexes.get(nick)
    if not hexes:
        return None
    if len(hexes) == 1:
        return hexes[0]
    return tuple(hexes)


def rect64_to_xywh01(rect64: str) -> tuple[float, float, float, float]:
    """Convert Picasa rect64 to (x_center, y_center, width, height) normalized [0,1].

    Args:
        rect64: Hexadecimal string representing left, top, right, bottom as 4 packed uint16s.

    Returns:
        Tuple of (x_center, y_center, width, height) as floats in [0, 1].

    Example:
        >>> rect64_to_xywh01("00000000ffffffff")
        (0.5, 0.5, 1.0, 1.0)
    """
    # Pad to 16 hex digits, extract 4 uint16 values (left, top, right, bottom)
    padded = rect64.rjust(16, "0")
    left = int(padded[0:4], 16) / 0xFFFF
    top = int(padded[4:8], 16) / 0xFFFF
    right = int(padded[8:12], 16) / 0xFFFF
    bottom = int(padded[12:16], 16) / 0xFFFF

    x_center = (left + right) / 2
    y_center = (top + bottom) / 2
    width = right - left
    height = bottom - top

    return (x_center, y_center, width, height)


def xywh01_to_rect64(x: float, y: float, w: float, h: float) -> str:
    """Convert normalized coordinates to Picasa rect64 format.

    Args:
        x: Center x coordinate [0, 1].
        y: Center y coordinate [0, 1].
        w: Width [0, 1].
        h: Height [0, 1].

    Returns:
        16-character hexadecimal string.

    Example:
        >>> xywh01_to_rect64(0.5, 0.5, 1.0, 1.0)
        '00000000ffffffff'
    """
    left = int((x - w / 2) * 0xFFFF)
    top = int((y - h / 2) * 0xFFFF)
    right = int((x + w / 2) * 0xFFFF)
    bottom = int((y + h / 2) * 0xFFFF)

    return f"{left:04x}{top:04x}{right:04x}{bottom:04x}"


def _contact_hr_to_face_type(contact_hex: str) -> str:
    """Determine face type from contact information.

    Args:
        contact_hex: Contact ID hex string.

    Returns:
        One of: Face, Pet, Toy, UnknownPerson, MetaPhoto, Arts2D, Arts3D, FalsePositive.
    """
    _load_contacts()
    contact = GLOBAL.hex_to_details.get(contact_hex.lower())
    if not contact:
        return "Face"

    name = contact.get("name", "")
    emails = contact.get("emails", [])

    # Check email markers
    is_pet = "pet@type.umann.hu" in emails
    is_stuffed = "stuffed@type.umann.hu" in emails

    # Apply Perl logic using match/case to keep a single return path.
    face_type = "Face"
    match True:
        case _ if re.match(r"^(q|UN)", name):
            face_type = "UnknownPerson"
        case _ if "ArtiFacial" in name:
            if "Photo" in name:
                face_type = "MetaPhoto"
            elif "Graph" in name:
                face_type = "Arts2D"
            else:
                face_type = "FalsePositive"
        case _ if re.search(r"sculpture|szobor", name, re.IGNORECASE):
            face_type = "Arts3D"
        case _ if is_pet:
            face_type = "Pet"
        case _ if re.search(r"minifigure", name, re.IGNORECASE) or is_stuffed:
            face_type = "Toy"

    return face_type


def _face_type_to_region_type(face_type: str) -> str:
    """Map face type to XMP region type."""
    if face_type.lower() in {"pet", "face"}:
        return face_type
    return "Face"


def _face_type_to_is_ignorable(face_type: str) -> bool:
    """Determine if face type should be marked ignorable."""
    return bool(re.search(r"unknown|meta|arts|false", face_type, re.IGNORECASE))


# pylint: disable=too-many-locals
def faces_to_exif(faces: str | dict | list | None, metadata: dict[str, t.Any]) -> dict[str, t.Any] | None:
    """Convert Picasa faces string to XMP RegionInfo structure.

    Args:
        faces: Picasa faces string (e.g., "rect64(abc),def;rect64(123),456"),
               dict with 'faces' key, list of face strings, or None.
        metadata: Metadata dict containing image dimensions (File:ImageWidth/Height).

    Returns:
        Dict with RegionInfo structure, or None if no faces or no change needed.

    The returned structure matches XMP-mwg-rs:RegionInfo format:
        {
            "XMP-mwg-rs:RegionInfo": {
                "AppliedToDimensions": {"W": width, "H": height, "Unit": "pixel"},
                "RegionList": [
                    {
                        "Area": {"X": x, "Y": y, "W": w, "H": h, "Unit": "normalized"},
                        "Name": contact_name,
                        "Type": region_type,
                        "Extensions": {
                            "XMP-Umann:FaceID": contact_hex,
                            "XMP-Umann:FaceNamespace": "http://umann.hu/kornel/picasa/1.0/",
                            "XMP-Umann:FaceRect64": rect64,
                            "XMP-Umann:FaceType": face_type,
                            "XMP-Umann:FaceIgnorable": "True" if ignorable else omitted or "False"
                        }

                    },
                    ...
                ]
            }
        }
    """
    # Normalize faces input
    if isinstance(faces, dict):
        faces = faces.get("faces")
    if faces is None or faces == "":
        return None
    if isinstance(faces, str):
        faces = [f.strip() for f in faces.split(";") if f.strip()]
    if not isinstance(faces, list):
        faces = [faces]

    # Parse faces
    face_re = re.compile(r"rect64\(([0-9a-f]{1,16})\),([0-9a-f]{1,16})", re.IGNORECASE)
    region_list = []

    for face_str in sorted(faces, key=lambda f: face_re.search(f).group(2) if face_re.search(f) else ""):
        match = face_re.search(face_str)
        if not match:
            continue

        rect64, contact_hex = match.group(1).lower(), match.group(2).lower()

        # Get contact info
        contact_name = nick_of_hex(contact_hex)
        if not contact_name:
            continue

        # Determine face type and region attributes
        face_type = _contact_hr_to_face_type(contact_hex)
        region_type = _face_type_to_region_type(face_type)
        is_ignorable = _face_type_to_is_ignorable(face_type)

        # Convert rect64 to normalized coordinates
        x, y, w, h = rect64_to_xywh01(rect64)

        # Build region
        extensions = {
            "XMP-Umann:FaceID": contact_hex,
            "XMP-Umann:FaceNamespace": get_config("picasa.namespace"),
            "XMP-Umann:FaceRect64": rect64,
            "XMP-Umann:FaceType": face_type,
        }
        if is_ignorable:
            extensions["XMP-Umann:FaceIgnorable"] = "True"

        region = {
            "Area": {"X": x, "Y": y, "W": w, "H": h, "Unit": "normalized"},
            "Name": contact_name,
            "Type": region_type,
            "Extensions": extensions,
        }
        region_list.append(region)

    if not region_list:
        return None

    # Get image dimensions from metadata
    width = metadata.get("File:ImageWidth") or metadata.get("File", {}).get("ImageWidth")
    height = metadata.get("File:ImageHeight") or metadata.get("File", {}).get("ImageHeight")

    if not width or not height:
        raise ValueError(f"Missing image dimensions in metadata: width={width}, height={height}")

    # Build RegionInfo structure
    region_info = {
        "AppliedToDimensions": {"W": str(width), "H": str(height), "Unit": "pixel"},
        "RegionList": region_list,
    }

    # Check if this differs from existing metadata
    existing = metadata.get("XMP-mwg-rs:RegionInfo") or metadata.get("XMP", {}).get("RegionInfo")
    if existing == region_info:
        return None

    return {"XMP-mwg-rs:RegionInfo": region_info}


# imported dynamically by src/umann/metadata/memoize.py
def get_picasa_metadata(ini_fname: str) -> dict[str, dict[str, t.Any]]:  # noqa
    """Extract Picasa metadata from a .picasa.ini sidecar file.

    Args:
        ini_fname: Path to the .picasa.ini file.
    """
    retval = {}
    section = None
    with open(ini_fname, encoding="utf8") as infh:
        for line in map(str.lstrip, infh.read().splitlines()):
            if match := re.search(r"^\s*$", line):
                continue
            if match := re.search(r"^\[(.*)\]$", line):
                section = match[1]
                if section in retval:
                    raise PicasaIniError(f"get_picasa_metadata({ini_fname}): {section=} twice")
                retval[section] = {}
                continue
            if not section:
                raise PicasaIniError(f"get_picasa_metadata({ini_fname}): No section for {line=}")
            if match := re.search(r"([^=]+)=(.+)", line):
                key, val = match[1], match[2]
                if "." not in key and key not in "backuphash" and "faces_found_by" not in key:
                    retval[section][key] = val
                continue
            raise PicasaIniError(f"get_picasa_metadata({ini_fname}): Invalid {line=} in {section=}")
    return retval


if __name__ == "__main__":
    print(nick_of_hex(sys.argv[1]))
