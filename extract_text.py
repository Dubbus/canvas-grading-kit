#!/usr/bin/env python3
"""
Flatten each student's PDF/DOCX submission to plain text for grading.

Usage:
    python3 extract_text.py <assignment_dir>            # writes <assignment_dir>/_text/<student>.txt
    python3 extract_text.py <assignment_dir> --only Doe_Jane_1234567 ...

Output conventions (so a text-only reader knows what it can't see):
    === page N ===                       page boundary (PDF exact; DOCX from Word's saved page breaks)
    [figure: page N, 2 images]           PDF: raster images on that page
    [figure ~p3]  [chart ~p3]            DOCX: an image or chart at this spot (~ = approximate page)
    | cell | cell |                      DOCX table rows, one per line

Each file starts with a header: source file, page count, image count.
Needs `pdftotext`/`pdfimages` (poppler) for PDFs; DOCX is parsed directly.
Vector graphics in PDFs (e.g. charts exported from Excel/Word) are not detected as images;
use `render_pages.py`, which also picks pages by their Figure/Table captions.
"""
import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
CAPTION = re.compile(r"^\s*(Figure|Table)\s+[A-Z]?\d+", re.M)
MIN_IMG_PX = 40  # ignore tiny icons/bullets


# --------------------------------------------------------------------------- PDF
def pdf_image_pages(path: Path):
    """{page: image count} for raster images at least MIN_IMG_PX on both sides."""
    out = subprocess.run(["pdfimages", "-list", str(path)], capture_output=True, text=True).stdout
    counts = {}
    for line in out.splitlines()[2:]:
        cols = line.split()
        if len(cols) > 4 and cols[0].isdigit():
            if int(cols[3]) >= MIN_IMG_PX and int(cols[4]) >= MIN_IMG_PX:
                counts[int(cols[0])] = counts.get(int(cols[0]), 0) + 1
    return counts


def pdf_pages(path: Path):
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True).stdout
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def pdf_text(path: Path):
    pages = pdf_pages(path)
    imgs = pdf_image_pages(path)
    body = []
    for i, p in enumerate(pages, 1):
        body.append(f"=== page {i} ===")
        if imgs.get(i):
            body.append(f"[figure: page {i}, {imgs[i]} image{'s' if imgs[i] > 1 else ''}]")
        body.append(_squeeze(p))
    return "\n".join(body), f"pages={len(pages)} images={sum(imgs.values())}"


# --------------------------------------------------------------------------- DOCX
class _DocxWalker:
    """Walk document.xml in reading order, skipping mc:Fallback duplicates."""

    def __init__(self):
        self.page = 1
        self.saw_page_marks = False
        self.images = 0

    def text(self, el, top=True):
        if el.tag == MC + "Fallback":
            return
        tag = el.tag
        if tag in (W + "lastRenderedPageBreak",) or (tag == W + "br" and el.get(W + "type") == "page"):
            self.page += 1
            self.saw_page_marks = True
        elif tag in (W + "t", M + "t"):
            yield el.text or ""
        elif tag == W + "tab":
            yield " "
        elif tag in (W + "drawing", W + "pict"):
            # a drawing may be a picture, a chart, or just a text box (often holding a caption)
            chart = any((g.get("uri") or "").endswith("/chart") for g in el.iter(A + "graphicData"))
            picture = any(True for _ in el.iter(A + "blip")) or any(True for _ in el.iter(V + "imagedata"))
            if chart or picture:
                self.images += 1
                yield f" [{'chart' if chart else 'figure'} ~p{self.page}] "
        elif tag == W + "p" and not top:
            yield "\n"  # paragraph inside a text box
        for child in el:
            yield from self.text(child, top=False)

    def paragraph(self, p):
        return "".join(self.text(p)).strip()

    def table(self, tbl):
        rows = []
        for tr in tbl.findall(W + "tr"):
            cells = []
            for tc in tr.findall(W + "tc"):
                parts = [self.block(b) for b in tc if b.tag in (W + "p", W + "tbl", W + "sdt")]
                cells.append(" ".join(x for x in parts if x).replace("|", "/"))
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        return "\n".join(rows)

    def block(self, el):
        if el.tag == W + "p":
            return self.paragraph(el)
        if el.tag == W + "tbl":
            return self.table(el)
        if el.tag == W + "sdt":  # content controls wrap ordinary paragraphs/tables
            content = el.find(W + "sdtContent")
            return "\n".join(filter(None, (self.block(c) for c in (content if content is not None else []))))
        return ""


def docx_text(path: Path):
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    w = _DocxWalker()
    lines = [w.block(el) for el in (body if body is not None else [])]
    text = "\n".join(l for l in lines if l)
    if not w.saw_page_marks:  # no saved page breaks (e.g. Google Docs export): page numbers meaningless
        text = re.sub(r" ~p\d+\]", "]", text)
    pages = w.page if w.saw_page_marks else "?"
    return _squeeze(text), f"pages~{pages} images={w.images}"


# --------------------------------------------------------------------------- main
def _squeeze(s):
    s = re.sub(r"[ \t]{3,}", "   ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def student_dirs(assignment_dir: Path, only=None):
    for sdir in sorted(p for p in assignment_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if not only or sdir.name in only:
            yield sdir


def submission_files(sdir: Path):
    return sorted(f for f in sdir.iterdir() if f.suffix.lower() in (".pdf", ".docx"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("assignment_dir", type=Path)
    ap.add_argument("--only", nargs="*", help="student folder names to process")
    args = ap.parse_args()

    out_dir = args.assignment_dir / "_text"
    out_dir.mkdir(exist_ok=True)
    for sdir in student_dirs(args.assignment_dir, args.only):
        files = submission_files(sdir)
        if not files:
            print(f"{sdir.name}: no pdf/docx", file=sys.stderr)
            continue
        parts = []
        for f in files:
            body, meta = pdf_text(f) if f.suffix.lower() == ".pdf" else docx_text(f)
            parts.append(f"### {f.name}  [{meta}]\n{body}")
        text = "\n\n".join(parts) + "\n"
        (out_dir / f"{sdir.name}.txt").write_text(text, encoding="utf-8")
        figs = len(re.findall(r"\[(figure|chart)", text))
        tables = len(re.findall(r"^\| .* \|$", text, re.M))
        print(f"{sdir.name}: {len(text)} chars, {figs} figure markers, {tables} table rows")


if __name__ == "__main__":
    main()
