#!/usr/bin/env python3
"""
optimize_epub.py - Optimize EPUB images for low-RAM e-paper devices (Xteink X4, X3, M5Paper).
"""

import os
import sys
import glob
import shutil
import zipfile
import io
import argparse
from PIL import Image, ImageEnhance

PROFILES = {
    "x4": {"width": 480, "height": 800, "contrast": 1.10, "quality": 80},
    "x3": {"width": 528, "height": 792, "contrast": 1.10, "quality": 80},
    "m5paper": {"width": 540, "height": 960, "contrast": 1.10, "quality": 80},
    "safe": {"width": 600, "height": 800, "contrast": 1.10, "quality": 80},
}

def optimize_single_epub(src_path, dst_path, profile):
    max_w = profile["width"]
    max_h = profile["height"]
    contrast_f = profile["contrast"]
    quality = profile["quality"]

    with zipfile.ZipFile(src_path, "r") as zin:
        all_items = zin.infolist()
        mimetype_item = None
        other_items = []
        for item in all_items:
            if item.filename == "mimetype":
                mimetype_item = item
            else:
                other_items.append(item)

        with zipfile.ZipFile(dst_path, "w") as zout:
            # EPUB spec requirement: mimetype uncompressed and first
            if mimetype_item is not None:
                zout.writestr("mimetype", zin.read(mimetype_item.filename), compress_type=zipfile.ZIP_STORED)

            for item in other_items:
                data = zin.read(item.filename)
                fn_lower = item.filename.lower()
                if fn_lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    try:
                        img = Image.open(io.BytesIO(data))
                        orig_len = len(data)
                        orig_mode = img.mode

                        if orig_mode == "1":
                            if img.size[0] > max_w or img.size[1] > max_h:
                                img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                            img = img.convert("1")
                            buf = io.BytesIO()
                            img.save(buf, format="PNG", optimize=True)
                            new_data = buf.getvalue()
                            if len(new_data) < orig_len or img.size != Image.open(io.BytesIO(data)).size:
                                data = new_data
                        else:
                            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                                img = img.convert("RGBA")
                                bg = Image.new("RGB", img.size, (255, 255, 255))
                                bg.paste(img, mask=img.split()[3])
                                img = bg.convert("L")
                            else:
                                img = img.convert("L")

                            if img.size[0] > max_w or img.size[1] > max_h:
                                img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

                            if contrast_f != 1.0:
                                img = ImageEnhance.Contrast(img).enhance(contrast_f)

                            buf = io.BytesIO()
                            if fn_lower.endswith(".png"):
                                img.save(buf, format="PNG", optimize=True)
                            else:
                                img.save(buf, format="JPEG", quality=quality, optimize=True)

                            new_data = buf.getvalue()
                            if len(new_data) < orig_len or img.size != Image.open(io.BytesIO(data)).size:
                                data = new_data
                    except Exception as e:
                        print(f"    Warning processing image {item.filename}: {e}", file=sys.stderr)

                zout.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)

def process_file(filepath, profile, backup=True, inplace=True, out_dir=None):
    orig_size = os.path.getsize(filepath)
    filename = os.path.basename(filepath)
    file_dir = os.path.dirname(os.path.abspath(filepath))

    if backup:
        backup_dir = os.path.join(file_dir, "_backup_original")
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, filename)
        if not os.path.exists(backup_file):
            shutil.copy2(filepath, backup_file)

    if inplace:
        tmp_dst = filepath + ".x4tmp"
        optimize_single_epub(filepath, tmp_dst, profile)
        os.replace(tmp_dst, filepath)
        final_path = filepath
    else:
        dest_dir = out_dir or file_dir
        os.makedirs(dest_dir, exist_ok=True)
        final_path = os.path.join(dest_dir, filename)
        tmp_dst = final_path + ".x4tmp"
        optimize_single_epub(filepath, tmp_dst, profile)
        os.replace(tmp_dst, final_path)

    new_size = os.path.getsize(final_path)
    pct = (1 - (new_size / orig_size)) * 100
    print(f"  {filename}: {orig_size/(1024*1024):.2f} MB -> {new_size/(1024*1024):.2f} MB (-{pct:.1f}%)")
    return orig_size, new_size

def main():
    parser = argparse.ArgumentParser(description="Optimize EPUB images for e-paper devices.")
    parser.add_argument("target", help="Path to EPUB file or directory of EPUBs")
    parser.add_argument("--profile", choices=list(PROFILES.keys()), default="x4", help="Target device profile (default: x4)")
    parser.add_argument("--no-backup", action="store_true", help="Do not create _backup_original backup")
    parser.add_argument("--out-dir", help="Output directory (defaults to in-place replacement)")
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    print(f"Using profile '{args.profile}': {profile['width']}x{profile['height']}, Grayscale, Contrast {profile['contrast']}x, JPEG Q{profile['quality']}")

    if os.path.isdir(args.target):
        files = sorted(glob.glob(os.path.join(args.target, "*.epub")))
        if not files:
            print(f"No .epub files found in {args.target}")
            return
        print(f"Found {len(files)} books in {args.target}")
        t_before, t_after = 0, 0
        for f in files:
            b, a = process_file(f, profile, backup=not args.no_backup, inplace=(args.out_dir is None), out_dir=args.out_dir)
            t_before += b
            t_after += a
        saved = (t_before - t_after) / (1024*1024)
        print(f"\nTotal: {t_before/(1024*1024):.2f} MB -> {t_after/(1024*1024):.2f} MB (Saved: {saved:.2f} MB, -{(1-t_after/t_before)*100:.1f}%)")
    else:
        process_file(args.target, profile, backup=not args.no_backup, inplace=(args.out_dir is None), out_dir=args.out_dir)

if __name__ == "__main__":
    main()
