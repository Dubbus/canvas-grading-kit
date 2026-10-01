#!/usr/bin/env python3
"""
Render the pages of each submission that hold figures or tables to PNG, for a human skim
or a local vision model (e.g. Ollama with qwen2.5vl / gemma3 / llama3.2-vision).

Usage:
    python3 render_pages.py <assignment_dir>                    # pages with images or Figure/Table captions
    python3 render_pages.py <assignment_dir> --all              # every page
    python3 render_pages.py <assignment_dir> --only Doe_Jane_1234567 --dpi 100

Writes <assignment_dir>/_pages/<student>/p03.png. Needs `pdftoppm` (poppler).
DOCX files are converted to PDF first with LibreOffice (`soffice`) if it's installed;
otherwise they're skipped with a message. Nothing leaves your machine.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from extract_text import CAPTION, pdf_image_pages, pdf_pages, student_dirs, submission_files

SOFFICE_PATHS = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def find_soffice():
    return shutil.which("soffice") or shutil.which("libreoffice") or next(
        (p for p in SOFFICE_PATHS if os.path.exists(p)), None)


def docx_to_pdf(soffice, docx: Path, out_dir: Path):
    """Convert with a throwaway LibreOffice profile so it works even if LibreOffice is open."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([soffice, f"-env:UserInstallation=file://{Path(profile).as_posix()}",
                        "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx)],
                       capture_output=True, timeout=180)
    pdf = out_dir / (docx.stem + ".pdf")
    return pdf if pdf.exists() else None


def pages_to_render(pdf: Path, every=False):
    texts = pdf_pages(pdf)
    if every:
        return list(range(1, len(texts) + 1))
    imgs = pdf_image_pages(pdf)
    return sorted({p for p in imgs} | {i for i, t in enumerate(texts, 1) if CAPTION.search(t)})


def render(pdf: Path, pages, dest: Path, dpi, prefix=""):
    if pages:
        dest.mkdir(parents=True, exist_ok=True)
    for p in pages:
        out = dest / f"{prefix}p{p:02d}"
        subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", str(dpi), "-png", "-singlefile",
                        str(pdf), str(out)], capture_output=True)
    return len(pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("assignment_dir", type=Path)
    ap.add_argument("--only", nargs="*", help="student folder names to process")
    ap.add_argument("--all", action="store_true", help="render every page, not just figure/table pages")
    ap.add_argument("--dpi", type=int, default=80, help="resolution (default 80: readable, small)")
    args = ap.parse_args()

    if not shutil.which("pdftoppm"):
        sys.exit("pdftoppm not found. Install poppler (macOS: brew install poppler).")
    soffice = find_soffice()
    root = args.assignment_dir / "_pages"
    skipped_docx = []

    for sdir in student_dirs(args.assignment_dir, args.only):
        files = submission_files(sdir)
        total, picked = 0, []
        for i, f in enumerate(files):
            pdf = f
            if f.suffix.lower() == ".docx":
                if not soffice:
                    skipped_docx.append(sdir.name)
                    continue
                pdf = docx_to_pdf(soffice, f, root / "_converted" / sdir.name)
                if not pdf:
                    print(f"{sdir.name}: LibreOffice could not convert {f.name}", file=sys.stderr)
                    continue
            pages = pages_to_render(pdf, args.all)
            prefix = f"f{i + 1}_" if len(files) > 1 else ""
            total += render(pdf, pages, root / sdir.name, args.dpi, prefix)
            picked += [f"{prefix}{p}" for p in pages]
        if files:
            print(f"{sdir.name}: {total} page(s) rendered" + (f" ({', '.join(map(str, picked))})" if picked else ""))

    if skipped_docx:
        print(f"\nSkipped {len(skipped_docx)} DOCX submission(s): LibreOffice not found.\n"
              "Install it to render Word files (macOS: brew install --cask libreoffice; "
              "Windows/Linux: libreoffice.org), or have students submit PDFs.")
    print(f"\nImages are in {root}")


if __name__ == "__main__":
    main()
