#!/usr/bin/env python3
"""
Post drafted rubric scores from an assignment's _drafts.csv to Canvas, one student at a time.

Dry run by default: prints what would be sent and changes nothing.

    python3 post_grades.py <assignment_dir> --student Doe_Jane_1234567           # dry run
    python3 post_grades.py <assignment_dir> --student Doe_Jane_1234567 --send    # really post

Safety:
  * Fetches the student's live rubric assessment first and re-sends every existing criterion's
    points, rating and comment unchanged, so the other grader's rows and any rubric comments survive
    (Canvas replaces the whole assessment on save).
  * Refuses to change a criterion that already has a different live score unless --overwrite.
  * Only touches the rubric. Submission comments and PDF (DocViewer) annotations are separate objects
    and are not sent or modified. comment_for_student is NOT posted.
  * Appends every send to <assignment_dir>/_posted.log (before/after JSON).
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

from canvas_pull import Canvas, get_config


def draft_points(row, criteria):
    """Map draft columns 'R<n> ...' to {criterion_id: points} for non-empty cells."""
    out = {}
    for col, val in row.items():
        m = re.match(r"R(\d+) ", col or "")
        if m and val not in ("", None):
            out[criteria[int(m.group(1)) - 1]["id"]] = float(val)
    return out


def rating_for(criterion, points):
    return next((r["id"] for r in criterion.get("ratings") or [] if float(r["points"]) == points), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("assignment_dir", type=Path)
    ap.add_argument("--student", action="append", required=True, help="folder name from _drafts.csv (repeatable)")
    ap.add_argument("--send", action="store_true", help="actually post (default: dry run)")
    ap.add_argument("--overwrite", action="store_true", help="allow changing criteria that already have a different score")
    args = ap.parse_args()

    d = args.assignment_dir
    course_id = int(d.parent.parent.name.split("_")[0])
    assignment_id = int(d.name.split("_")[0])
    criteria = json.loads((d / "rubric.json").read_text())["criteria"]
    by_id = {c["id"]: c for c in criteria}
    drafts = {r["folder"]: r for r in csv.DictReader(open(d / "_drafts.csv", encoding="utf-8"))}

    api = Canvas(*get_config())
    sub_path = f"/courses/{course_id}/assignments/{assignment_id}/submissions"

    for folder in args.student:
        if folder not in drafts:
            sys.exit(f"{folder} not in _drafts.csv")
        user_id = folder.rsplit("_", 1)[1]
        live = api.get(f"{sub_path}/{user_id}", **{"include[]": ["rubric_assessment"]})
        before = live.get("rubric_assessment") or {}
        want = draft_points(drafts[folder], criteria)

        merged, changes, conflicts = {}, [], []
        for c in criteria:
            cid = c["id"]
            cur = before.get(cid) or {}
            entry = {k: cur.get(k) for k in ("points", "rating_id", "comments") if cur.get(k) not in (None, "")}
            if cid in want:
                old = cur.get("points")
                if old is not None and float(old) != want[cid] and not args.overwrite:
                    conflicts.append(f"{c['description']}: live {old} vs draft {want[cid]}")
                    continue
                if old is None or float(old) != want[cid]:
                    changes.append(f"{c['description'][:55]:55} {old if old is not None else '-':>5} -> {want[cid]}")
                    entry["points"] = want[cid]
                    entry["rating_id"] = rating_for(c, want[cid]) or entry.get("rating_id")
            if entry:
                merged[cid] = entry

        print(f"\n{folder} (user {user_id})  live score {live.get('score')}")
        if conflicts:
            print("  CONFLICT, skipping student:\n    " + "\n    ".join(conflicts))
            continue
        if not changes:
            print("  nothing to change")
            continue
        print("  changes:\n    " + "\n    ".join(changes))
        kept = [by_id[k]["description"][:40] for k, v in merged.items() if k not in want]
        print(f"  kept as-is: {len(kept)} criteria" +
              ("; with comments: " + ", ".join(by_id[k]['description'][:30] for k, v in merged.items() if v.get('comments')) if any(v.get('comments') for v in merged.values()) else ""))
        new_total = sum(v.get("points") or 0 for k, v in merged.items() if not by_id[k].get("ignore_for_scoring"))
        print(f"  rubric total after: {new_total}")

        form = []
        for cid, v in merged.items():
            for k, val in v.items():
                form.append((f"rubric_assessment[{cid}][{k}]", val))
        if not args.send:
            print("  (dry run, nothing sent)")
            continue

        result = api.put(f"{sub_path}/{user_id}", form)
        after = api.get(f"{sub_path}/{user_id}", **{"include[]": ["rubric_assessment", "submission_comments"]})
        lost = [by_id[k]["description"] for k in before
                if (before[k] or {}).get("comments") and (after.get("rubric_assessment") or {}).get(k, {}).get("comments") != before[k]["comments"]]
        print(f"  SENT. score now {after.get('score')}" + (f"  !! comments changed on: {lost}" if lost else ""))
        with open(d / "_posted.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "student": folder, "user_id": user_id,
                                "before": before, "sent": merged,
                                "after": after.get("rubric_assessment"), "score_after": after.get("score")}) + "\n")


if __name__ == "__main__":
    main()
