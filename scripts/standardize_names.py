#!/usr/bin/env python3
"""
standardize_names.py - Standardize and sanitize e-book filenames for e-readers.

Formats series books into: {two_digit_number} - {title}.epub
Formats standalone books into: {title} - {author}.epub

Handles:
- Extracting volume numbers from [Series NN] or (Series NN)
- Padding single-digit numbers with leading zero (e.g. 1 -> 01)
- Handling omnibus volume ranges (e.g. 01-03 -> 01-03)
- Stripping junk release tags: (retail), (epub), v3.1(RTF), etc.
- Fixing squished compound words from OCR/Calibre rips (e.g. "Knight'sCastle" -> "Knight's Castle")
- Resolving/mapping unnumbered sequels via --number
- Pre-checking for filename collisions
- Full dry-run preview mode
"""

import os
import sys
import re
import argparse
import shutil

# Common release/rip tags to strip from titles
JUNK_TAG_PATTERNS = [
    r'\s*\(retail\)',
    r'\s*\[retail\]',
    r'\s*\(epub\)',
    r'\s*\[epub\]',
    r'\s*v\d+\.\d+\s*(?:\([a-zA-Z0-9]+\))?',
    r'\s*\(siPDF\)',
    r'\s*\(unabridged\)',
]

# Common squished patterns from OCR/Calibre filename generation
SQUISHED_WORD_FIXES = {
    "Knight'sCastle": "Knight's Castle",
    "Magic by theLake": "Magic by the Lake",
    "The TimeGarden": "The Time Garden",
    "Magic orNot": "Magic or Not",
    "TheWell-Wishers": "The Well-Wishers",
    "Seven-DayMagic": "Seven-Day Magic",
    "andobfuscation": "and obfuscation",
}


def clean_title(title: str) -> str:
    """Sanitize title text by removing release tags and fixing spacing."""
    t = title.strip()

    # Strip junk tags
    for pat in JUNK_TAG_PATTERNS:
        t = re.sub(pat, '', t, flags=re.IGNORECASE)

    # Apply known squished fixes
    for squished, fixed in SQUISHED_WORD_FIXES.items():
        t = t.replace(squished, fixed)

    # Fix obvious squished lowercase-Uppercase words where words run together (e.g. "DayMagic" -> "Day Magic")
    # But preserve hyphenated terms like "Seven-Day"
    t = re.sub(r'([a-z])([A-Z])', r'\1 \2', t)

    # Clean redundant spaces
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def parse_filename(filename: str):
    """
    Parse an epub filename into (number_str, title, author, series).
    Returns (None, title, author, None) if not a series match.
    """
    base, ext = os.path.splitext(filename)
    if ext.lower() != ".epub":
        return None

    # Pattern 1: Author - [Series NN - Subseries MM] - Title
    m_sub = re.match(
        r'^(.*?)\s*-\s*[\[\(](.*?)\s+(\d+)\s*-\s*(.*?)\s+(\d+)[\]\)]\s*-\s*(.*?)$',
        base
    )
    if m_sub:
        author, s1, n1, s2, n2, title = m_sub.groups()
        num_str = f"{int(n1):02d}"
        return num_str, clean_title(title), author.strip(), f"{s1.strip()} ({s2.strip()} {int(n2):02d})"

    # Pattern 2: Multi-volume omnibus, e.g. Author - [Series 01-03] - Title
    m_omni = re.match(
        r'^(.*?)\s*-\s*[\[\(](.*?)\s+(\d+)\s*[-–]\s*(\d+)[\]\)]\s*-\s*(.*?)$',
        base
    )
    if m_omni:
        author, series, n_start, n_end, title = m_omni.groups()
        num_str = f"{int(n_start):02d}-{int(n_end):02d}"
        return num_str, clean_title(title), author.strip(), series.strip()

    # Pattern 3: Standard series: Author - [Series NN] - Title or Author - (Series NN) - Title
    m_std = re.match(
        r'^(.*?)\s*-\s*[\[\(](.*?)\s+(\d+)[\]\)]\s*-\s*(.*?)$',
        base
    )
    if m_std:
        author, series, num, title = m_std.groups()
        num_str = f"{int(num):02d}"
        return num_str, clean_title(title), author.strip(), series.strip()

    # Pattern 4: Already standardized: NN - Title or NN-MM - Title
    m_already = re.match(r'^(\d+(?:-\d+)?)\s*-\s*(.*?)$', base)
    if m_already:
        num_str, title = m_already.groups()
        # If single digit, pad it
        if num_str.isdigit():
            num_str = f"{int(num_str):02d}"
        return num_str, clean_title(title), None, None

    # Pattern 5: Author - Title (standalone)
    m_author = re.match(r'^(.*?)\s*-\s*(.*?)$', base)
    if m_author:
        author, title = m_author.groups()
        return None, clean_title(title), author.strip(), None

    # Fallback: Just the title
    return None, clean_title(base), None, None


def get_epub_metadata(path: str):
    """Attempt to extract dc:title and dc:creator from the EPUB's content.opf."""
    try:
        import zipfile
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(path, 'r') as z:
            for name in z.namelist():
                if name.endswith('.opf'):
                    tree = ET.fromstring(z.read(name))
                    title, creator = None, None
                    for el in tree.iter():
                        if el.tag.endswith('title') and not title and el.text:
                            title = el.text.strip()
                        if el.tag.endswith('creator') and not creator and el.text:
                            creator = el.text.strip()
                    return title, creator
    except Exception:
        pass
    return None, None


def plan_renames(files, standalone=False, manual_number=None):
    """Generate a list of (src_path, new_filename) pairs and check collisions."""
    plan = []
    seen_dest = {}

    for path in sorted(files):
        filename = os.path.basename(path)
        parsed_num, title, author, series = parse_filename(filename)

        # Allow CLI override for unnumbered sequels
        if manual_number is not None and len(files) == 1:
            parsed_num = f"{int(manual_number):02d}" if manual_number.isdigit() else manual_number

        # Use metadata from inside the EPUB if available to verify title and author
        meta_title, meta_creator = get_epub_metadata(path) if os.path.isfile(path) else (None, None)

        if standalone:
            # Standalone format: Title - Author.epub
            if meta_title and meta_creator:
                clean_t = clean_title(meta_title)
                clean_a = meta_creator.strip()
                new_name = f"{clean_t} - {clean_a}.epub"
            elif author:
                # Check if author was actually title (e.g. "The Phantom Tollbooth - Norton Juster")
                if meta_title and clean_title(author).lower() == meta_title.lower():
                    new_name = f"{clean_title(author)} - {title}.epub"
                else:
                    new_name = f"{title} - {author}.epub"
            else:
                new_name = f"{title}.epub"
        else:
            if parsed_num:
                new_name = f"{parsed_num} - {title}.epub"
            elif meta_title and meta_creator:
                new_name = f"{clean_title(meta_title)} - {meta_creator.strip()}.epub"
            elif author:
                new_name = f"{title} - {author}.epub"
            else:
                new_name = f"{title}.epub"

        # Check collisions
        if new_name in seen_dest:
            print(f"Error: Collision detected! Both '{filename}' and '{seen_dest[new_name]}' map to '{new_name}'.",
                  file=sys.stderr)
            return None

        seen_dest[new_name] = filename
        plan.append((path, new_name))

    return plan


def update_opf_metadata(epub_path, title=None, author=None, series=None, index=None):
    """Update internal OPF metadata in the EPUB file using ebook-meta."""
    ebook_meta = shutil.which("ebook-meta")
    if not ebook_meta:
        alt = os.path.expanduser("~/.local/bin/ebook-meta")
        if os.path.exists(alt):
            ebook_meta = alt
    if not ebook_meta:
        return False

    cmd = [ebook_meta, epub_path]
    if title:
        cmd.extend(["--title", title])
    if author:
        # Normalize "Last, First" to "First Last" if comma present
        if "," in author:
            parts = [p.strip() for p in author.split(",", 1)]
            author = f"{parts[1]} {parts[0]}"
        cmd.extend(["--authors", author])
    if series:
        cmd.extend(["--series", series])
    if index is not None:
        # If range like 01-03, take start number
        idx_val = str(index).split("-")[0]
        cmd.extend(["--index", idx_val])

    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Standardize filenames and embed clean OPF metadata for e-readers and Calibre."
    )
    parser.add_argument("target", nargs="+", help="One or more EPUB files or directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview renames without executing")
    parser.add_argument("--standalone", action="store_true", help="Format as 'Title - Author.epub' instead of series format")
    parser.add_argument("--number", help="Manual series number for single unnumbered file (e.g. --number 37)")
    parser.add_argument("--series", help="Explicit series name override")
    parser.add_argument("--author", help="Explicit author name override")
    parser.add_argument("--no-opf", action="store_true", help="Skip updating internal EPUB OPF metadata")
    parser.add_argument("--out-dir", help="Move/copy to target directory instead of renaming in place")
    args = parser.parse_args()

    files = []
    for item in args.target:
        if os.path.isdir(item):
            for f in sorted(os.listdir(item)):
                if f.endswith(".epub"):
                    files.append(os.path.join(item, f))
        elif os.path.isfile(item) and item.endswith(".epub"):
            files.append(item)

    if not files:
        print("No .epub files found to process.")
        return

    plan = plan_renames(files, standalone=args.standalone, manual_number=args.number)
    if plan is None:
        sys.exit(1)

    print(f"Found {len(plan)} files to process:")
    changes_count = 0

    for src_path, new_filename in plan:
        src_dir = os.path.dirname(os.path.abspath(src_path))
        dest_dir = os.path.abspath(args.out_dir) if args.out_dir else src_dir
        dest_path = os.path.join(dest_dir, new_filename)

        orig_name = os.path.basename(src_path)
        is_change = (src_path != dest_path)
        if is_change:
            changes_count += 1

        parsed_num, parsed_title, parsed_author, parsed_series = parse_filename(orig_name)
        if args.number and len(files) == 1:
            parsed_num = args.number
        if args.series:
            parsed_series = args.series
        if args.author:
            parsed_author = args.author

        prefix = "  [RENAME]" if is_change else "  [OK]    "
        if args.dry_run:
            opf_info = f" (OPF: Title='{parsed_title}', Author='{parsed_author}', Series='{parsed_series}', Index={parsed_num})" if not args.no_opf else ""
            print(f"{prefix} {orig_name}\n         -> {new_filename}{opf_info}")
        else:
            if is_change:
                os.makedirs(dest_dir, exist_ok=True)
                if args.out_dir:
                    shutil.copy2(src_path, dest_path)
                    print(f"  [COPIED] {orig_name} -> {dest_path}")
                else:
                    os.rename(src_path, dest_path)
                    print(f"  [RENAMED] {orig_name} -> {new_filename}")
            else:
                print(f"  [UNCHANGED] {orig_name}")

            # Embed clean metadata into content.opf
            if not args.no_opf:
                ok = update_opf_metadata(
                    dest_path,
                    title=parsed_title,
                    author=parsed_author,
                    series=parsed_series,
                    index=parsed_num
                )
                if ok:
                    print(f"    [OPF UPDATED] Embedded series/author/title into {new_filename}")

    if args.dry_run:
        print(f"\n[DRY RUN COMPLETE] {changes_count} of {len(plan)} files will be updated.")
    else:
        print(f"\n[COMPLETE] {changes_count} files successfully updated.")


if __name__ == "__main__":
    main()
