#!/usr/bin/env python3
"""
One entry point for the whole kit. Run with no arguments for help.

    python3 grade.py setup       # first run: save Canvas URL + token, check tools, list your courses
    python3 grade.py doctor      # re-check config, token and tools without changing anything
    python3 grade.py download    # pick course -> assignments, download submissions + rubrics
    python3 grade.py extract     # pick a downloaded assignment, flatten PDFs/DOCX to _text/
    python3 grade.py condense    # print student-written content only (boilerplate removed)
    python3 grade.py post        # dry-run posting _drafts.csv rows marked approved (add --send to post)

Anything after the subcommand is passed through, e.g.
    python3 grade.py post --student Doe_Jane_1234567 --send
    python3 grade.py download --course 12345 --assignment 678
"""
import getpass
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / ".env"
EXPORT = HERE / "canvas_export"
sys.path.insert(0, str(HERE))


# --------------------------------------------------------------------------- helpers
def ask(prompt, default=""):
    val = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return val or default


def read_env():
    vals = {}
    if ENV.is_file():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip("'\"")
    return vals


def normalize_url(url):
    url = url.strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def check_token(base, token):
    """Return (ok, message)."""
    from canvas_pull import Canvas
    try:
        me = Canvas(base, token).get("/users/self")
        return True, f"signed in as {me.get('name')}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Canvas rejected the token (401). Generate a new one under Account -> Settings."
        return False, f"HTTP {e.code} from Canvas"
    except urllib.error.URLError as e:
        return False, f"can't reach {base}: {e.reason}"


def check_tools():
    """Return list of (tool, found, hint)."""
    hint = {"darwin": "brew install poppler", "win32": "choco install poppler  (or: scoop install poppler)"} \
        .get(sys.platform, "sudo apt install poppler-utils")
    return [(t, bool(shutil.which(t)), hint) for t in ("pdftotext", "pdfimages")]


def print_tools():
    ok = True
    for tool, found, hint in check_tools():
        print(f"  {'ok ' if found else 'MISSING'}  {tool}" + ("" if found else f"   -> {hint}"))
        ok &= found
    if not ok:
        print("  (only needed for `extract` on PDF submissions; everything else works without it)")


def assignment_dirs():
    return sorted(p for p in EXPORT.glob("*/submissions/*") if p.is_dir())


def pick_assignment_dir(args):
    """Use a path from args if given, else let the user pick a downloaded assignment."""
    if args and not args[0].startswith("-") and Path(args[0]).is_dir():
        return Path(args[0]), args[1:]
    dirs = assignment_dirs()
    if not dirs:
        sys.exit("No downloaded assignments yet. Run: python3 grade.py download")
    print("\nDownloaded assignments:")
    for i, d in enumerate(dirs, 1):
        n = sum(1 for p in d.iterdir() if p.is_dir() and not p.name.startswith("_"))
        flags = [f for f, ok in (("text", (d / "_text").is_dir()), ("drafts", (d / "_drafts.csv").is_file())) if ok]
        print(f"  {i:>2}. {d.parent.parent.name[:40]} / {d.name}  ({n} submissions"
              + (f"; has {', '.join(flags)}" if flags else "") + ")")
    choice = ask("Pick #", "1" if len(dirs) == 1 else "")
    if not choice.isdigit() or not 1 <= int(choice) <= len(dirs):
        sys.exit("No assignment picked.")
    return dirs[int(choice) - 1], args


def run(script, *argv):
    return subprocess.call([sys.executable, str(HERE / script), *map(str, argv)])


# --------------------------------------------------------------------------- commands
def cmd_setup(_args):
    print("Canvas grading kit setup. Student data stays on this computer.\n")
    cur = read_env()
    base = normalize_url(ask("Your Canvas URL (e.g. https://myschool.instructure.com)", cur.get("CANVAS_URL", "")))
    if not base:
        sys.exit("A Canvas URL is required.")
    print("\nCreate a token in Canvas: Account -> Settings -> + New Access Token.")
    print("Paste it below (input is hidden). Press Enter to keep the saved one.")
    token = getpass.getpass("Token: ").strip() or cur.get("CANVAS_TOKEN", "")
    if not token:
        sys.exit("A token is required.")

    ok, msg = check_token(base, token)
    print(f"\nToken check: {msg}")
    if not ok:
        sys.exit("Nothing saved. Fix the URL/token and run setup again.")

    ENV.write_text(f"CANVAS_URL={base}\nCANVAS_TOKEN={token}\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass
    print(f"Saved to {ENV.name} (readable only by you; git-ignored).")

    print("\nTools:")
    print_tools()

    os.environ["CANVAS_URL"], os.environ["CANVAS_TOKEN"] = base, token
    from canvas_pull import Canvas
    from canvas_submissions import grader_courses, print_courses
    print_courses(grader_courses(Canvas(base, token)))
    print("\nNext: python3 grade.py download")


def cmd_doctor(_args):
    cur = read_env()
    base = normalize_url(os.environ.get("CANVAS_URL") or cur.get("CANVAS_URL", ""))
    token = os.environ.get("CANVAS_TOKEN") or cur.get("CANVAS_TOKEN", "")
    print(f"  {'ok ' if ENV.is_file() else 'MISSING'}  .env" + ("" if ENV.is_file() else "   -> python3 grade.py setup"))
    if ENV.is_file() and sys.platform != "win32" and ENV.stat().st_mode & 0o077:
        print("  WARN  .env is readable by other users   -> chmod 600 .env")
    if base and token:
        ok, msg = check_token(base, token)
        print(f"  {'ok ' if ok else 'FAIL'}  token: {msg}")
    print_tools()
    print(f"  info  {len(assignment_dirs())} downloaded assignment(s) in {EXPORT.name}/")


def cmd_download(args):
    if not ENV.is_file() and not os.environ.get("CANVAS_TOKEN"):
        sys.exit("Not set up yet. Run: python3 grade.py setup")
    sys.exit(run("canvas_submissions.py", "--out", EXPORT, *args))


def cmd_extract(args):
    d, rest = pick_assignment_dir(args)
    sys.exit(run("extract_text.py", d, *rest))


def cmd_condense(args):
    d, rest = pick_assignment_dir(args)
    if not (d / "_text").is_dir():
        print("No _text/ yet; extracting first.")
        run("extract_text.py", d)
    sys.exit(run("condense.py", d, *rest))


def cmd_post(args):
    d, rest = pick_assignment_dir(args)
    if not (d / "_drafts.csv").is_file():
        sys.exit(f"No _drafts.csv in {d.name}. See README: '_drafts.csv format'.")
    if "--student" not in rest and "--approved" not in rest:
        rest = ["--approved", *rest]
    sys.exit(run("post_grades.py", d, *rest))


COMMANDS = {"setup": cmd_setup, "doctor": cmd_doctor, "download": cmd_download,
            "extract": cmd_extract, "condense": cmd_condense, "post": cmd_post}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip())
        sys.exit(0 if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help") else 2)
    try:
        COMMANDS[sys.argv[1]](sys.argv[2:])
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")


if __name__ == "__main__":
    main()
