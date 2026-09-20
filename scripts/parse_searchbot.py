#!/usr/bin/env python3
"""
parse_searchbot.py - Parse SearchBot/Searchook result files into ranked, clean IRC triggers.
"""

import sys
import os
import re
import zipfile
import argparse
import json

BOT_PRIORITY = {
    "bsk": 100,
    "ashurbanipal": 90,
    "oatmeal": 80,
    "horla": 70,
    "firebound": 60,
    "wench": 50,
    "peapod": 40,
    "ook": 30,
    "pondering-ebooks2": 20,
    "dumbledore": -100,  # Known stalled/broken transfers
}

def extract_lines(filepath):
    if filepath.endswith(".zip"):
        with zipfile.ZipFile(filepath, "r") as z:
            txt_files = [f for f in z.namelist() if f.endswith(".txt")]
            if not txt_files:
                raise ValueError("No .txt file found inside zip")
            content = z.read(txt_files[0]).decode("utf-8", errors="replace")
    else:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    return content.splitlines()

def score_trigger(line):
    # Only epubs
    if not re.search(r'\.epub(\s|$|::)', line, re.IGNORECASE):
        return -1000

    bot_match = re.match(r'^!([a-zA-Z0-9_\-]+)\s+', line)
    if not bot_match:
        return -1000

    bot = bot_match.group(1).lower()
    bot_score = BOT_PRIORITY.get(bot, 10)

    score = bot_score
    if re.search(r'\(retail\)', line, re.IGNORECASE):
        score += 25
    if re.search(r'\[[a-zA-Z0-9\s]+ \d+\]', line):
        score += 15
    if "v5." in line or "v1." in line:
        score += 5

    return score

def clean_trigger(line):
    # Remove ::INFO:: and everything after
    line = re.sub(r'\s*::.*$', '', line).strip()
    return line

def extract_title_key(trigger):
    m = re.match(r'^!\S+\s+(.*)$', trigger)
    if not m:
        return trigger
    payload = m.group(1)
    cleaned = re.sub(r'\.epub.*$', '', payload, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(retail\)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(epub\)', '', cleaned, flags=re.IGNORECASE)
    # Normalize brackets and parentheses around series/numbers
    cleaned = re.sub(r'[\[\(]([^\]\)]*?)[\]\)]', r' \1 ', cleaned)
    # Remove author prefix if standard
    cleaned = re.sub(r'^[a-zA-Z\s\.]+\s+-\s+', '', cleaned)
    # Normalize numbering padding (e.g. 01 -> 1)
    cleaned = re.sub(r'\b0+(\d+)\b', r'\1', cleaned)
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()
    return cleaned

def parse_results(filepath, preferred_bot=None):
    lines = extract_lines(filepath)
    scored = []

    for line in lines:
        line = line.strip()
        if not line.startswith("!"):
            continue
        sc = score_trigger(line)
        if sc <= -500:
            continue

        clean = clean_trigger(line)
        key = extract_title_key(clean)
        
        # Override bot priority if user specified preferred_bot
        if preferred_bot:
            bot_match = re.match(r'^!([a-zA-Z0-9_\-]+)', clean)
            if bot_match and bot_match.group(1).lower() == preferred_bot.lower():
                sc += 200

        scored.append((sc, key, clean))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate by title key
    seen = set()
    deduped = []
    for sc, key, clean in scored:
        if key not in seen:
            seen.add(key)
            deduped.append(clean)

    # Natural sort by title/series
    def natural_key(text):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

    deduped.sort(key=natural_key)
    return deduped

def main():
    parser = argparse.ArgumentParser(description="Parse SearchBot result files into clean IRC triggers.")
    parser.add_argument("file", help="Path to SearchBot results .txt or .txt.zip")
    parser.add_argument("--bot", help="Force/prefer specific bot (e.g. Bsk)")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size for output (default: 4)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    triggers = parse_results(args.file, preferred_bot=args.bot)

    if args.json:
        batches = [triggers[i:i + args.batch_size] for i in range(0, len(triggers), args.batch_size)]
        print(json.dumps({"total": len(triggers), "batches": batches, "triggers": triggers}, indent=2))
    else:
        for idx, t in enumerate(triggers, 1):
            batch_num = ((idx - 1) // args.batch_size) + 1
            print(f"[{batch_num}] {t}")

if __name__ == "__main__":
    main()
