#!/usr/bin/env python3
"""Presence checklist for a lab-report template assignment. Usage: template_checks.py <assignment_dir>"""
import csv, re, sys
from pathlib import Path
d = Path(sys.argv[1])
scores = {r["folder"]: r["score"] for r in csv.DictReader(open(d / "_submissions.csv")) if r["folder"]}
checks = {
    "title":   lambda t: not re.search(r"Title of the Experiment", t),
    "seats":   lambda t: bool(re.search(r"Seat \d", t)),
    "day":     lambda t: bool(re.search(r"(Mon|Tues|Wednes|Thurs|Fri)day", t)),
    "expdate": lambda t: bool(re.search(r"Date of Experiment:\s*\d", t)),
    "testproc":lambda t: bool(re.search(r"Testing Procedure", t)),
    "eq1ref":  lambda t: bool(re.search(r"Equation ?1", t)),
    "eq23":    lambda t: bool(re.search(r"Equations 2 and 3", t)),
    "table1":  lambda t: bool(re.search(r"Table 1:", t)),
    "fig2ss":  lambda t: bool(re.search(r"Figure \d: Spot Speed", t)),
    "ref3":    lambda t: bool(re.search(r"\[3\]\s*Spot Speed Write Up", t)),
    "appD":    lambda t: bool(re.search(r"APPENDIX D|Appendix D\b", t)),
    "tblC1":   lambda t: bool(re.search(r"Table C ?1", t)),
    "C1cite":  lambda t: bool(re.search(r"Table C ?1[^\n]*\[3\]", t)),
}
print(f"{'student':28} {'score':>5} " + " ".join(f"{k:>8}" for k in checks))
for f in sorted((d / "_text").glob("*.txt"), key=lambda f: (scores.get(f.stem) != "", f.stem)):
    t = f.read_text(encoding="utf-8")
    print(f"{f.stem[:28]:28} {scores.get(f.stem) or '--':>5} " +
          " ".join(f"{'.' if fn(t) else 'MISS':>8}" for fn in checks.values()))
