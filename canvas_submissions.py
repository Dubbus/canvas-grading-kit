#!/usr/bin/env python3
"""
List the Canvas courses you teach / grade, show their assignments, and download
every student submission for the assignments you pick.

Usage:
    python3 canvas_submissions.py                          # interactive: course -> assignments -> download
    python3 canvas_submissions.py --list                   # list courses you're a teacher/TA in and exit
    python3 canvas_submissions.py --course 12345           # list that course's assignments, then ask
    python3 canvas_submissions.py --course 12345 --assignment 678 --assignment 679
    python3 canvas_submissions.py --course 12345 --all     # download submissions for every assignment

Auth: same CANVAS_TOKEN / CANVAS_URL (.env) as canvas_pull.py.

Original author: @jayson-clark (https://github.com/jayson-clark), used with permission.
"""
import argparse
import csv
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from canvas_pull import SSL_CTX, Canvas, front_matter, get_config, slug
from html2md import html_to_markdown

GRADER_TYPES = {"teacher": "Teacher", "ta": "TA"}


# --------------------------------------------------------------------------- courses
def grader_courses(api: Canvas):
    """Courses where one of the user's enrollments is teacher or TA."""
    # Filtering by course `state` hides concluded/archived courses, so ask per enrollment type.
    by_id = {}
    for etype, role in GRADER_TYPES.items():
        for c in api.paginate("/courses", enrollment_type=etype, **{"include[]": ["term"]}):
            if c.get("id") and c.get("name"):
                by_id.setdefault(c["id"], c).setdefault("_roles", []).append(role)
    return sorted(by_id.values(), key=lambda c: c["id"])


def print_courses(courses):
    if not courses:
        print("You don't have any teacher or TA enrollments.")
        return
    print("\nCourses you grade:")
    for c in courses:
        term = (c.get("term") or {}).get("name", "")
        print(f"  {c['id']:>8}  {c['name']}" + (f"  [{term}]" if term else "")
              + f"  ({', '.join(c['_roles'])})")


def pick_course(api: Canvas):
    print_courses(grader_courses(api))
    print()
    cid = input("Course ID: ").strip()
    if not cid.isdigit():
        sys.exit("Need a numeric course ID.")
    return int(cid)


# --------------------------------------------------------------------------- assignments
def list_assignments(api: Canvas, course_id):
    assignments = list(api.paginate(f"/courses/{course_id}/assignments",
                                    order_by="position"))
    if not assignments:
        print("No assignments in this course.")
        return assignments
    print(f"\n  {'#':>3}  {'ID':>8}  {'Due':<10}  {'ToGrade':>7}  Name")
    for i, a in enumerate(assignments, 1):
        due = (a.get("due_at") or "")[:10] or "-"
        needs = a.get("needs_grading_count")
        pub = "" if a.get("published", True) else "  (unpublished)"
        print(f"  {i:>3}  {a['id']:>8}  {due:<10}  "
              f"{'' if needs is None else needs:>7}  {a.get('name')}{pub}")
    return assignments


def choose_assignments(assignments):
    print()
    raw = input("Download submissions for which # (e.g. 3 or 1,4-6 or 'all'; blank to quit): ").strip()
    if not raw:
        return []
    if raw.lower() == "all":
        return assignments
    picked = []
    for part in raw.split(","):
        part = part.strip()
        try:
            if "-" in part:
                lo, hi = (int(x) for x in part.split("-", 1))
                nums = range(lo, hi + 1)
            else:
                nums = [int(part)]
        except ValueError:
            sys.exit(f"Can't parse {part!r}.")
        for n in nums:
            if not 1 <= n <= len(assignments):
                sys.exit(f"#{n} is out of range (1-{len(assignments)}).")
            if assignments[n - 1] not in picked:
                picked.append(assignments[n - 1])
    return picked


# --------------------------------------------------------------------------- submissions
def student_label(sub):
    user = sub.get("user") or {}
    name = user.get("sortable_name") or user.get("name")
    if name:
        return f"{slug(name, 40)}_{sub.get('user_id')}"
    # anonymous grading hides the user
    return f"anon_{sub.get('anonymous_id') or sub.get('id')}"


def fetch_file(api: Canvas, url, dest: Path):
    """Submission file URLs carry their own verifier and redirect to a file host that
    rejects the forwarded Bearer token, so try without auth first."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r, open(dest, "wb") as f:
            while chunk := r.read(65536):
                f.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403):
            raise
        api.download(url, dest)


def save_submission(api: Canvas, sub, dest: Path):
    """Write everything retrievable for one submission into `dest`. Returns list of notes."""
    dest.mkdir(parents=True, exist_ok=True)
    notes = []
    stype = sub.get("submission_type")

    for att in sub.get("attachments") or []:
        fname = slug(att.get("display_name") or att.get("filename") or f"file_{att.get('id')}", 100)
        path = dest / fname
        if path.exists() and path.stat().st_size == att.get("size"):
            continue  # already downloaded on a previous run
        try:
            fetch_file(api, att["url"], path)
        except Exception as e:
            notes.append(f"download failed for {fname}: {e}")

    if sub.get("body"):
        (dest / "submission.md").write_text(html_to_markdown(sub["body"]), encoding="utf-8")

    if sub.get("url"):
        (dest / "submission_url.txt").write_text(sub["url"] + "\n", encoding="utf-8")

    media = sub.get("media_comment") or {}
    if media.get("url"):
        ext = ".mp4" if media.get("media_type") == "video" else ".mp3"
        path = dest / f"media{ext}"
        if not path.exists():
            try:
                fetch_file(api, media["url"], path)
            except Exception as e:
                notes.append(f"media download failed: {e}")

    entries = sub.get("discussion_entries") or []
    if entries:
        md = []
        for e in entries:
            md += [f"## {e.get('created_at', '')}", "", html_to_markdown(e.get("message") or ""), ""]
        (dest / "discussion_entries.md").write_text("\n".join(md), encoding="utf-8")

    if stype == "online_quiz":
        notes.append("quiz submission: answers aren't downloadable via this API; review in SpeedGrader")

    comments = sub.get("submission_comments") or []
    if comments:
        md = []
        for c in comments:
            md += [f"**{c.get('author_name', '?')}** — {c.get('created_at', '')}", "",
                   c.get("comment") or "", ""]
        (dest / "comments.md").write_text("\n".join(md), encoding="utf-8")

    return notes


# --------------------------------------------------------------------------- rubrics
def _cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def rubric_markdown(assignment):
    s = assignment.get("rubric_settings") or {}
    md = [f"# Rubric: {s.get('title') or assignment.get('name')}", "",
          front_matter([("Rubric ID", s.get("id")),
                        ("Points possible", s.get("points_possible")),
                        ("Used for grading", assignment.get("use_rubric_for_grading")),
                        ("Free-form comments", s.get("free_form_criterion_comments"))]), ""]
    for i, c in enumerate(assignment["rubric"], 1):
        md += [f"## {i}. {c.get('description')} ({c.get('points')} pts)", ""]
        if c.get("long_description"):
            md += [c["long_description"], ""]
        if c.get("criterion_use_range"):
            md += ["_Scored as a range._", ""]
        if c.get("ignore_for_scoring"):
            md += ["_Not counted toward the score._", ""]
        md += ["| Points | Rating | Details |", "|---:|---|---|"]
        for r in c.get("ratings") or []:
            md.append(f"| {r.get('points')} | {_cell(r.get('description'))} | {_cell(r.get('long_description'))} |")
        md.append("")
    return "\n".join(md)


def rubric_assessment_markdown(rubric, assessment):
    md = ["| # | Criterion | Points | Rating | Comments |", "|---:|---|---:|---|---|"]
    total = 0
    for i, c in enumerate(rubric, 1):
        a = assessment.get(c["id"]) or {}
        rating = next((r for r in c.get("ratings") or [] if r.get("id") == a.get("rating_id")), {})
        pts = a.get("points")
        if pts is not None and not c.get("ignore_for_scoring"):
            total += pts
        md.append(f"| {i} | {_cell(c.get('description'))} | {'' if pts is None else pts} / {c.get('points')} "
                  f"| {_cell(rating.get('description'))} | {_cell(a.get('comments'))} |")
    md += ["", f"**Rubric total:** {total}"]
    return "\n".join(md)


def rubric_columns(rubric, assessment):
    """Per-criterion points for the CSV (blank when not assessed)."""
    assessment = assessment or {}
    cols = {}
    for i, c in enumerate(rubric, 1):
        pts = (assessment.get(c["id"]) or {}).get("points")
        cols[f"R{i} {c.get('description')} (/{c.get('points')})"] = pts
    return cols


def download_assignment(api: Canvas, course_id, assignment, root: Path):
    aid = assignment["id"]
    adir = root / f"{aid}_{slug(assignment.get('name'))}"
    adir.mkdir(parents=True, exist_ok=True)
    print(f"\n{assignment.get('name')} ({aid})")
    print(f"  -> {adir}")

    rubric = assignment.get("rubric") or []
    if rubric:
        (adir / "rubric.md").write_text(rubric_markdown(assignment), encoding="utf-8")
        (adir / "rubric.json").write_text(json.dumps(
            {"settings": assignment.get("rubric_settings"), "criteria": rubric}, indent=2), encoding="utf-8")
        print(f"  rubric: {len(rubric)} rows")

    subs = list(api.paginate(f"/courses/{course_id}/assignments/{aid}/submissions",
                             **{"include[]": ["user", "submission_comments", "rubric_assessment"]}))
    rows = []
    count = 0
    for sub in subs:
        submitted = sub.get("workflow_state") != "unsubmitted" and sub.get("submitted_at")
        label = student_label(sub)
        notes = []
        if submitted:
            count += 1
            print(f"  [{count}] {label}")
            notes = save_submission(api, sub, adir / label)
            for n in notes:
                print(f"       ! {n}")
        user = sub.get("user") or {}
        rows.append({
            "student": user.get("sortable_name") or user.get("name") or label,
            "user_id": sub.get("user_id"),
            "folder": label if submitted else "",
            "workflow_state": sub.get("workflow_state"),
            "submission_type": sub.get("submission_type"),
            "submitted_at": sub.get("submitted_at"),
            "attempt": sub.get("attempt"),
            "late": sub.get("late"),
            "missing": sub.get("missing"),
            "score": sub.get("score"),
            "grade": sub.get("grade"),
            "notes": "; ".join(notes),
        })
        if rubric:
            assessment = sub.get("rubric_assessment")
            rows[-1].update(rubric_columns(rubric, assessment))
            if assessment:
                (adir / label).mkdir(parents=True, exist_ok=True)
                (adir / label / "rubric_assessment.md").write_text(
                    rubric_assessment_markdown(rubric, assessment), encoding="utf-8")

    if rows:
        with open(adir / "_submissions.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"  {count} submitted / {len(subs)} students")


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Download Canvas assignment submissions for courses you grade.")
    ap.add_argument("--course", type=int, help="course ID (skips the course picker)")
    ap.add_argument("--assignment", type=int, action="append",
                    help="assignment ID to download (repeatable; skips the assignment picker)")
    ap.add_argument("--all", action="store_true", help="download submissions for every assignment")
    ap.add_argument("--list", action="store_true", help="list courses you're a teacher/TA in and exit")
    ap.add_argument("--out", default="canvas_export", help="output directory (default: canvas_export)")
    args = ap.parse_args()

    base, token = get_config()
    api = Canvas(base, token)

    if args.list:
        print_courses(grader_courses(api))
        return

    course_id = args.course or pick_course(api)
    course = api.get(f"/courses/{course_id}")
    course_name = course.get("name", f"course_{course_id}")
    root = Path(args.out).resolve() / f"{course_id}_{slug(course_name)}" / "submissions"
    print(f"\nCourse: {course_name} ({course_id})")

    if args.assignment:
        chosen = [api.get(f"/courses/{course_id}/assignments/{aid}") for aid in args.assignment]
    else:
        assignments = list_assignments(api, course_id)
        if not assignments:
            return
        chosen = assignments if args.all else choose_assignments(assignments)

    for a in chosen:
        download_assignment(api, course_id, a, root)
    if chosen:
        print(f"\nDone. Submissions are in {root}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit("HTTP 401: Canvas rejected the token. Generate a new one under "
                     "Account -> Settings -> + New Access Token.")
        if e.code == 403:
            sys.exit("HTTP 403: you don't have permission for that (are you a teacher/TA in this course?).")
        sys.exit(f"HTTP {e.code} {e.reason} from Canvas.")
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, socket.gaierror):
            sys.exit(f"Can't resolve that hostname. Check CANVAS_URL in .env ({reason})")
        if isinstance(reason, ssl.SSLError):
            sys.exit(f"TLS error talking to Canvas: {reason}")
        sys.exit(f"Network error: {reason}")
