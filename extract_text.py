#!/usr/bin/env python3
"""
Flatten each student's PDF/DOCX submission to plain text for grading.

Usage:
    python3 extract_text.py <assignment_dir>            # writes <assignment_dir>/_text/<student>.txt
    python3 extract_text.py <assignment_dir> --only Doe_Jane_1234567 ...

Each output starts with a one-line header: source file, page count (PDF), image count.
Pages are separated by lines of the form '=== page N ==='. Needs `pdftotext`/`pdfimages` (poppler).
"""
import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def pdf_text(path: Path):
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True).stdout
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    imgs = subprocess.run(["pdfimages", "-list", str(path)], capture_output=True, text=True).stdout
    n_img = max(0, len(imgs.strip().splitlines()) - 2)
    body = "\n".join(f"=== page {i} ===\n{_squeeze(p)}" for i, p in enumerate(pages, 1))
    return body, f"pages={len(pages)} images={n_img}"


def docx_text(path: Path):
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        n_img = sum(1 for n in z.namelist() if n.startswith("word/media/"))
    lines = []
    for el in root.iter():
        if el.tag == W + "p":
            # includes Word equation text (m:t) and table cell paragraphs
            txt = "".join(t.text or "" for t in el.iter() if t.tag.endswith("}t"))
            if el.find(f".//{W}br[@{W}type='page']") is not None:
                lines.append("=== page break ===")
            lines.append(txt)
    return _squeeze("\n".join(lines)), f"pages=? images={n_img}"


def _squeeze(s):
    s = re.sub(r"[ \t]{3,}", "   ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("assignment_dir", type=Path)
    ap.add_argument("--only", nargs="*", help="student folder names to process")
    args = ap.parse_args()

    out_dir = args.assignment_dir / "_text"
    out_dir.mkdir(exist_ok=True)
    for sdir in sorted(p for p in args.assignment_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if args.only and sdir.name not in args.only:
            continue
        files = [f for f in sdir.iterdir() if f.suffix.lower() in (".pdf", ".docx")]
        if not files:
            print(f"{sdir.name}: no pdf/docx", file=sys.stderr)
            continue
        parts = []
        for f in files:
            body, meta = pdf_text(f) if f.suffix.lower() == ".pdf" else docx_text(f)
            parts.append(f"### {f.name}  [{meta}]\n{body}")
        (out_dir / f"{sdir.name}.txt").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        print(f"{sdir.name}: {len(parts[-1])} chars")


if __name__ == "__main__":
    main()
