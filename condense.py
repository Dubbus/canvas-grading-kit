#!/usr/bin/env python3
"""
Condense extracted submissions (from extract_text.py) for review: drop template boilerplate
lines that most of the class shares, so only student-written content remains.

Usage:
    python3 condense.py <assignment_dir> [student_folder ...] [--common 0.5]
"""
import argparse
import re
from collections import Counter
from pathlib import Path


def norm(line):
    return re.sub(r"\s+", " ", line).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("assignment_dir", type=Path)
    ap.add_argument("students", nargs="*")
    ap.add_argument("--common", type=float, default=0.5,
                    help="drop lines found in at least this fraction of submissions")
    args = ap.parse_args()

    files = sorted((args.assignment_dir / "_text").glob("*.txt"))
    texts = {f.stem: [norm(l) for l in f.read_text(encoding="utf-8").splitlines()] for f in files}
    freq = Counter(l for lines in texts.values() for l in set(lines) if l)
    cutoff = args.common * len(texts)

    for name in args.students or sorted(texts):
        seen, kept = set(), []
        for l in texts[name]:
            if not l or l in seen or freq[l] >= cutoff or l.startswith("=== page"):
                continue
            seen.add(l)
            kept.append(l[:300])
        print(f"######## {name}  ({len(kept)} unique lines)")
        print("\n".join(kept))
        print()


if __name__ == "__main__":
    main()
