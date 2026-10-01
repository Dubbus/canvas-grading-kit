# canvas-grading-kit

Small, dependency-free Python scripts for TAs who grade in Canvas: download submissions and rubrics,
flatten reports to text for fast review (by you or an LLM), and post rubric scores back safely.

Standard library only (Python 3.8+). Text extraction from PDFs uses poppler's `pdftotext` / `pdfimages`
(`brew install poppler`).

> [!IMPORTANT]
> **Local models only. Do not send student data to cloud AI services.**
> Submissions, extracted text, drafts and grade logs are student education records (FERPA in the US).
> If you use an LLM to help draft grades, run it **on your own machine** (e.g. [Ollama](https://ollama.com),
> [llama.cpp](https://github.com/ggml-org/llama.cpp)). Do not paste or upload student work to hosted assistants
> (Anthropic/Claude, OpenAI/ChatGPT, Google/Gemini, Copilot, Cursor, etc.) unless your institution has explicitly
> approved that service for student records. These scripts themselves never contact any AI service; they only
> talk to your Canvas instance.

## Setup

```sh
cp .env.example .env     # fill in CANVAS_URL and CANVAS_TOKEN
python3 canvas_submissions.py --list
```

Create a token in Canvas under **Account → Settings → + New Access Token**. Treat it like a password:
it can do anything you can do in Canvas. `.env` is git-ignored.

## Workflow

| Step | Script | What it does |
|---|---|---|
| 1. Download | `canvas_submissions.py --course <id>` | Pick assignments; saves every submission, `rubric.md`/`rubric.json`, and `_submissions.csv` (status, late, score, per-criterion rubric points) |
| 2. Flatten | `extract_text.py <assignment_dir>` | PDF/DOCX → `_text/<student>.txt` with page and image counts |
| 3. Condense | `condense.py <assignment_dir> [student ...]` | Drops boilerplate lines most of the class shares, leaving only what each student wrote. Big token saver if an LLM is reading |
| 4. Draft | *you* | Write `<assignment_dir>/_drafts.csv` (format below) |
| 5. Post | `post_grades.py <assignment_dir> --student <folder>` | Dry run by default; add `--send` to post |

`examples/` has two assignment-specific helpers to adapt: `worksheet_tail.py` (pull just the graded answers
out of a fixed worksheet) and `template_checks.py` (presence checklist for a report-template assignment).

## `_drafts.csv` format

```
folder,R7 Teamwork (/2.5),R8 Reflection (/5.0),...,comment_for_student,note_for_TA
Doe_Jane_1234567,2.5,5,...,,
```

- `folder` is the student folder name from step 1 (ends in the Canvas user ID).
- Any column starting `R<n> ` sets rubric criterion *n* (1-based, in rubric order). Leave a cell blank to skip that criterion.
- Other columns are ignored by `post_grades.py`.

## Posting safety (`post_grades.py`)

Canvas replaces the **whole** rubric assessment on save, so a naive post wipes other graders' rows. This script:

- fetches the live assessment first and re-sends every existing criterion's points, rating and comment unchanged
  (works for split grading where TAs each own some rubric rows),
- refuses to change a criterion that already has a different live score unless `--overwrite`,
- only touches the rubric: submission comments and PDF annotations are never sent or modified,
- logs before/after JSON for every send to `_posted.log`.

Check whether your assignment uses **manual posting** before sending. With automatic posting, students
see grades as soon as they land.

## Drafting with a local model

`condense.py` output is compact enough to fit a local model's context. A minimal loop with Ollama:

```sh
for s in $(ls canvas_export/*/submissions/<assignment>/_text | sed 's/.txt$//'); do
  { cat canvas_export/*/submissions/<assignment>/rubric.md; echo; \
    python3 condense.py canvas_export/*/submissions/<assignment> "$s"; } \
  | ollama run <model> "Score this submission against the rubric above. Reply as CSV: folder,R1,...,comment" \
  >> drafts_raw.txt
done
```

Review every draft yourself before posting. A model's score is a starting point, not a grade.

## Student data protection

- **Nothing student-related is committed.** `.gitignore` excludes `.env`, `canvas_export/`, `_text/`,
  `_drafts.csv`, `_posted.log`, `_submissions.csv`, and all PDF/DOCX files.
- **AI coding assistants are told to stay out.** If you open this repo in an AI-enabled editor, these files
  block it from reading student data and your token:
  - `.claude/settings.json`: Claude Code deny rules
  - `.cursorignore`: Cursor
  - `.aiexclude`: Gemini Code Assist / Android Studio
  - `.aiignore`: JetBrains AI Assistant

  These are guardrails, not guarantees: each tool enforces its own file differently, and none of them stops
  you from pasting data in yourself. The real rule is the one above: keep student data on your machine.
- **Your Canvas token** lives only in `.env`. Revoke it in Canvas (Account → Settings) when you're done
  grading for the term.

## Credits

`canvas_submissions.py` was written by [@jayson-clark](https://github.com/jayson-clark) and is included with permission.

## License

MIT. See [LICENSE](LICENSE).
