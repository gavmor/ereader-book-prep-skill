# ereader-book-prep-skill

A complete pipeline for acquiring, parsing, optimizing, organizing, and syncing e-books for low-RAM e-paper devices (especially the **Xteink X4**, **X3**, and **M5Paper**), and syncing them to local SD cards and Calibre.

## Highlights

- **Hardware-Aware Image Optimization (`optimize_epub.py`):** Clamps illustrations and covers to screen bounds (e.g. 480×800), strips color to 8-bit grayscale, enhances contrast, and preserves 1-bit monochrome drawings to keep EPUB image decode RAM under 384 KB (preventing ESP32 crashes).
- **SearchBot Results Parsing (`parse_searchbot.py`):** Parses and ranks IRC `#ebooks` SearchBot results, prioritizing reliable bots (`!Bsk`, `!Ashurbanipal`) and clean retail EPUBs while deduplicating titles and batching requests.
- **Title Standardization & OPF Embedding (`standardize_names.py`):** Formats series books into `{two_digit_number} - {title}.epub` for alphabetical e-reader navigation while embedding `<dc:title>`, `<dc:creator>`, and Calibre series metadata directly into `content.opf`.
- **Sync & Safe Eject (`sync_books.py`):** Syncs optimized libraries to mounted SD cards and Calibre databases, automatically calling `os.sync()` to flush page cache buffers before drive removal.

## What's here

- `SKILL.md` — The complete agent skill instructions, hardware constraints, and workflow guide.
- `scripts/optimize_epub.py` — EPUB image downscaler and contrast optimizer for e-ink profiles (`x4`, `x3`, `m5paper`, `safe`).
- `scripts/parse_searchbot.py` — SearchBot trigger parser, scorer, and batch generator.
- `scripts/standardize_names.py` — E-reader filename standardizer and OPF metadata tagger.
- `scripts/sync_books.py` — Removable storage and Calibre database synchronizer.

## Installation

Clone or symlink into your agent skills directory (e.g., `~/.agents/skills/`):

```bash
git clone git@github.com:gavmor/ereader-book-prep-skill.git ~/.agents/skills/ereader-book-prep
```

See [`SKILL.md`](SKILL.md) for the complete workflow documentation.
