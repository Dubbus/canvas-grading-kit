#!/usr/bin/env python3
"""Print only the graded tail of each a structured worksheet worksheet (Unsuccessful teamwork + 4 questions),
with the worksheet's own prompt text stripped. Usage: worksheet_tail.py <assignment_dir> [student ...]"""
import re, sys
from pathlib import Path
PROMPTS = [r"Which stage of the design", r"process took the longest for", r"your group\? Which do you",
    r"think should have taken the", r"^\s*longest\?", r"What would you change", r"about your design approach,",
    r"and why\?", r"How did your team make", r"decisions about your design\?", r"Would you use the same",
    r"method for your next design", r"project\? Why or why not\?", r"Did everyone get the chance",
    r"to contribute equally to the", r"design\? What would you do", r"in the future to make sure",
    r"everyone.s ideas are heard\?", r"QUESTIONS:.*", r"with at least two sentences.*", r"\d\d/\d\d/\d\d\s+V\d+\s+\d+",
    r"=== page \d+ ===", r"^\s*Unsuccessful\s*$"]
d = Path(sys.argv[1]) / "_text"
names = sys.argv[2:] or sorted(f.stem for f in d.glob("*.txt"))
for n in names:
    t = (d / f"{n}.txt").read_text(encoding="utf-8")
    m = re.search(r"Successful", t)
    t = t[m.end():] if m else t
    m = re.search(r"\n[^\n]*Unsuccessful|approaches\?", t)  # skip the successful list
    out = []
    for line in t.splitlines():
        for p in PROMPTS:
            line = re.sub(p, " ", line)
        line = re.sub(r"\s{2,}", " ", line).strip()
        if line: out.append(line)
    print(f"######## {n}\n" + " / ".join(out) + "\n")
