# Soul Digest - Metadata-Free Content Hashing

Extract and hash the "soul" (metadata-free content) from media files. This allows comparing files to determine if they differ only in metadata.

## What is a "Soul"?

The **soul** is the core media data without metadata:
- **JPG**: Compressed image data (between SOS and EOI markers), excluding EXIF/JFIF headers
- **MP3**: Audio stream, excluding ID3v2 headers and ID3v1 trailers
- **MP4**: Movie data in the mdat atom
- **MOV**: Movie data in the mdat atom (QuickTime)
- **PNG**: IDAT chunks containing compressed image data
- **AVI**: Movie data in the LIST/movi chunk

By hashing the soul, you can:
- Detect if two files are identical except for metadata
- Compare images that have been re-tagged or had EXIF data modified
- Find duplicate media files regardless of metadata differences

## Usage

### Quick Start

```python
from umann.digest import soul

# Get MD5 hash of soul (default)
md5_hash = soul("photo.jpg")
print(md5_hash)  # e.g., "10c9e17c0ac4e1ab75807823cb567168"

# Compare two files
if soul("photo1.jpg") == soul("photo2.jpg"):
    print("Same image, different metadata!")
```

### Advanced Usage

```python
from umann.digest import Soul

# Get multiple fields
s = Soul("video.avi").compute()
offset, length, hash_val = s.result("offset", "length", "md5_soul")
print(f"Soul at offset {offset}, length {length} bytes, MD5: {hash_val}")

# Get the actual soul bytes
soul_bytes = s.result("soul")

# Use with in-memory content
content = Path("file.jpg").read_bytes()
hash_val = Soul(content=content).compute().result()
```

### Result Fields

Available fields for `result()`:
- `"md5_soul"` (default): MD5 hash of soul
- `"soul"`: Soul bytes
- `"offset"`: Start position of soul in file
- `"length"`: Length of soul in bytes
- `"md5"`: MD5 hash of entire file
- `"content"`: Entire file content
- `"size"`: File size in bytes

## Supported Formats

Current plugins:
- **JPG/JPG**: Extracts image stream between SOS (FF DA) and EOI (FF D9) markers
- **MP3**: Skips ID3v2 headers and ID3v1 trailers
- **MP4**: Extracts mdat (movie data) atom from ISO BMFF structure
- **MOV**: Extracts mdat (movie data) atom from QuickTime files
- **PNG**: Extracts IDAT chunks containing image data
- **AVI**: Finds LIST/movi chunk with video data

## How It Works

1. **Plugin System**: Each file format has a plugin that knows how to locate the soul
2. **Auto-Detection**: Plugins register themselves and are selected based on file extension or magic bytes
3. **Efficient Reading**: Files can be processed in-memory or streamed for large files

## Extending

Add your own plugin by subclassing `SoulPlugin`:

```python
from umann.digest.soul import Soul, SoulPlugin

class MyFormatPlugin(SoulPlugin):
    @classmethod
    def can_handle(cls, soul: Soul) -> bool:
        """Check if this plugin can handle the file."""
        return soul.file and soul.file.suffix.lower() == ".myformat"

    def handle(self) -> None:
        """Extract soul offset and length."""
        s = self.soul
        # Your extraction logic here
        s.offset = 100  # Where soul starts
        s.length = 500  # How long soul is

# Register the plugin
Soul.register_plugin(MyFormatPlugin)
```

## History

This is a Python port of the Perl `Umann::Digest::Soul` module, originally designed for comparing photos with different
EXIF metadata but identical image content.

## Testing

```bash
pytest tests/unit/umann/digest/test_soul.py -v
```

All tests should pass with 100% coverage of core functionality.
