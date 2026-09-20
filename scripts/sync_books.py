#!/usr/bin/env python3
"""
sync_books.py - Sync optimized books to mounted e-reader SD card and/or local Calibre library.
"""

import os
import sys
import glob
import shutil
import subprocess
import argparse
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BOOKS_DIR = os.path.expanduser("~/Documents/Books")

def detect_sd_card():
    # Common Linux automount locations
    candidates = [
        "/run/media/user/disk",
        "/run/media/user",
        "/media/user",
        "/mnt"
    ]
    for c in candidates:
        if os.path.ismount(c) and os.access(c, os.W_OK):
            return c
        if os.path.isdir(c):
            for sub in os.listdir(c):
                p = os.path.join(c, sub)
                if os.path.ismount(p) and os.access(p, os.W_OK):
                    return p
    return None

def sync_sd(books_dir, sd_path=None, dry_run=False, delete=False):
    target = sd_path or detect_sd_card()
    if not target or not os.path.exists(target):
        print("Error: No mounted SD card detected. Provide --sd-path or insert device.", file=sys.stderr)
        return False

    print(f"Syncing books from '{books_dir}' -> SD Card '{target}'...")
    rsync_cmd = [
        "rsync", "-avui",
        "--exclude=_backup*",
        "--exclude=.*",
        "--exclude=*.tmp*",
        "--exclude=*.x4tmp*",
    ]
    if delete:
        rsync_cmd.append("--delete")
    rsync_cmd.extend([
        f"{books_dir.rstrip('/')}/",
        f"{target.rstrip('/')}/"
    ])
    if dry_run:
        rsync_cmd.append("--dry-run")
        print("[DRY RUN MODE]")

    res = subprocess.run(rsync_cmd)
    if res.returncode == 0 and not dry_run:
        print("Flushing kernel buffers to SD card (sync)...")
        try:
            os.sync()
        except AttributeError:
            subprocess.run(["sync"])
        print("Sync complete. Safe to unmount or remove SD card.")
    return res.returncode == 0

def get_calibre_library_path():
    cfg = os.path.expanduser("~/.config/calibre/global.py.json")
    if os.path.exists(cfg):
        try:
            with open(cfg, "r") as f:
                data = json.load(f)
                return data.get("library_path")
        except Exception:
            pass
    return None

def is_fuse_mount(path):
    if not path or not os.path.exists(path):
        return False, None
    abs_path = os.path.abspath(os.path.expanduser(path))
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    mount_point, fstype = parts[1], parts[2]
                    if fstype.startswith("fuse") and abs_path.startswith(mount_point):
                        return True, fstype
    except Exception:
        pass
    return False, None

def sync_calibre(books_dir_or_file, dry_run=False, allow_duplicates=False, library_path=None):
    calibredb = shutil.which("calibredb")
    if not calibredb or not os.path.exists(calibredb):
        calibredb = os.path.expanduser("~/.local/bin/calibredb")
    if not os.path.exists(calibredb):
        print("Error: calibredb not found. Is Calibre installed?", file=sys.stderr)
        return False

    lib_path = library_path or get_calibre_library_path()
    if os.path.isdir(books_dir_or_file):
        files = []
        for root, dirs, fnames in os.walk(books_dir_or_file):
            if "_backup" in root:
                continue
            for f in fnames:
                if f.endswith(".epub"):
                    files.append(os.path.join(root, f))
    else:
        files = [books_dir_or_file]

    files = sorted(files)
    print(f"Found {len(files)} books to sync with Calibre.")
    if not files:
        return True

    if dry_run:
        for f in files:
            print(f"  [DRY RUN] Would add: {os.path.basename(f)}")
        return True

    # Detect if target library is on a FUSE mount (e.g. gcsfuse, s3fs)
    is_fuse, fstype = is_fuse_mount(lib_path)
    if is_fuse:
        print(f"Notice: Calibre library at '{lib_path}' is mounted via {fstype}.")
        print("Using fast local staging to avoid SQLite journal locking over object storage...")
        with tempfile.TemporaryDirectory(prefix="calibre_staging_") as staging_dir:
            src_db = os.path.join(lib_path, "metadata.db")
            stg_db = os.path.join(staging_dir, "metadata.db")
            if os.path.exists(src_db):
                shutil.copy2(src_db, stg_db)

            # Batch add to local staging
            cmd = [calibredb, "add", "--with-library", staging_dir]
            if allow_duplicates:
                cmd.append("-d")
            cmd.extend(files)

            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode != 0:
                print(f"Error adding books locally: {p.stderr.strip()}", file=sys.stderr)
                return False

            print(p.stdout.strip())
            if p.stderr.strip():
                print(p.stderr.strip())

            # Upload newly created author directories in parallel
            author_dirs = [
                d for d in os.listdir(staging_dir)
                if os.path.isdir(os.path.join(staging_dir, d)) and not d.startswith(".")
            ]

            def copy_author(author_dir):
                s = os.path.join(staging_dir, author_dir)
                d = os.path.join(lib_path, author_dir)
                shutil.copytree(s, d, dirs_exist_ok=True)
                return author_dir

            if author_dirs:
                print(f"Uploading {len(author_dirs)} author collection(s) to cloud mount...")
                with ThreadPoolExecutor(max_workers=8) as executor:
                    list(executor.map(copy_author, author_dirs))

            # Sync notes.db if updated
            stg_notes = os.path.join(staging_dir, ".calnotes", "notes.db")
            dst_notes = os.path.join(lib_path, ".calnotes", "notes.db")
            if os.path.exists(stg_notes):
                os.makedirs(os.path.dirname(dst_notes), exist_ok=True)
                shutil.copy2(stg_notes, dst_notes)

            # Sync metadata.db back to cloud mount
            print("Syncing updated metadata.db to cloud mount...")
            shutil.copy2(stg_db, src_db)
            print("Calibre cloud sync complete!")
            return True

    # Standard local library (or no library path specified)
    print(f"Batch adding {len(files)} books to Calibre...")
    cmd = [calibredb, "add"]
    if lib_path:
        cmd.extend(["--with-library", lib_path])
    if allow_duplicates:
        cmd.append("-d")
    cmd.extend(files)

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode == 0:
        print(p.stdout.strip())
        if p.stderr.strip():
            print(p.stderr.strip())
        print("Calibre sync complete!")
        return True
    else:
        print(f"Error syncing with Calibre: {p.stderr.strip() or p.stdout.strip()}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Sync books to SD card and/or Calibre library.")
    parser.add_argument("--source", default=DEFAULT_BOOKS_DIR, help=f"Source directory (default: {DEFAULT_BOOKS_DIR})")
    parser.add_argument("--sd", action="store_true", help="Sync to mounted SD card")
    parser.add_argument("--sd-path", help="Explicit SD card mount path")
    parser.add_argument("--calibre", action="store_true", help="Sync to local/cloud Calibre library")
    parser.add_argument("--library-path", help="Explicit Calibre library path")
    parser.add_argument("--duplicates", action="store_true", help="Allow adding duplicate books")
    parser.add_argument("--delete", action="store_true", help="Delete extraneous files from destination (prune deleted/renamed books)")
    parser.add_argument("--dry-run", action="store_true", help="Preview sync actions without writing")
    args = parser.parse_args()

    if not args.sd and not args.calibre:
        # Default to both if mounted/available
        sd_found = bool(detect_sd_card())
        print(f"Auto-detecting sync destinations: SD card={sd_found}, Calibre=True")
        if sd_found:
            sync_sd(args.source, args.sd_path, args.dry_run, args.delete)
        sync_calibre(args.source, args.dry_run, args.duplicates, args.library_path)
        return

    if args.sd:
        sync_sd(args.source, args.sd_path, args.dry_run, args.delete)
    if args.calibre:
        sync_calibre(args.source, args.dry_run, args.duplicates, args.library_path)

if __name__ == "__main__":
    main()

