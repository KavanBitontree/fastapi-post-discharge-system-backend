import json
import re
from pathlib import Path
from tqdm import tqdm

IN_PATH = Path("data/clean/pages_clean.jsonl")
OUT_PATH = Path("data/index/icd_records.jsonl")

# Set this if you want to skip front-matter pages
START_PAGE = 1  # change to e.g. 5, 10, 20 if needed

CODE_RE = re.compile(r"^([A-TV-Z][0-9][0-9A-TV-Z](?:\.[0-9A-TV-Z]{1,4})?)\s+(.+)$")
RANGE_RE = re.compile(r"^[A-TV-Z][0-9]{2}[A-TV-Z]?(?:\.[0-9A-TV-Z]+)?-[A-TV-Z][0-9]{2}[A-TV-Z]?(?:\.[0-9A-TV-Z]+)?\b")

NOTE_PREFIXES = (
    "Includes:", "Inclusion terms:", "Excludes1:", "Excludes2:",
    "Code first:", "Use additional code:", "Code also:",
    "Note:", "Notes:", "7th Character:", "7th character:",
)


def is_note_start(line: str) -> bool:
    return any(line.startswith(p) for p in NOTE_PREFIXES)


def parent_code(code: str):
    if "." not in code:
        return None
    left, right = code.split(".", 1)
    if len(right) <= 1:
        return left
    return f"{left}.{right[:-1]}"


def code_level(code: str) -> int:
    if "." not in code:
        return 1
    return 1 + len(code.split(".", 1)[1])


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    total = sum(1 for _ in IN_PATH.open("r", encoding="utf-8"))

    current = None
    records = []
    active_note_idx = None  # keeps multi-line note blocks together

    def flush_current():
        nonlocal current, active_note_idx
        if current:
            current["details"] = [x for x in current["details"] if x]
            current["notes"] = [x for x in current["notes"] if x]
            records.append(current)
        current = None
        active_note_idx = None

    with IN_PATH.open("r", encoding="utf-8") as fin:
        for line in tqdm(fin, total=total, desc="Building structured ICD index"):
            page_rec = json.loads(line)
            page = int(page_rec["page"])
            if page < START_PAGE:
                continue

            text = page_rec.get("text", "")
            lines = [ln.strip() for ln in text.split("\n")]

            for ln in lines:
                if not ln:
                    active_note_idx = None  # break note block on blank
                    continue

                m = CODE_RE.match(ln)
                if m:
                    flush_current()
                    code = m.group(1)
                    title = m.group(2).strip()

                    current = {
                        "code": code,
                        "title": title,
                        "page": page,
                        "level": code_level(code),
                        "parent_code": parent_code(code),
                        "details": [],
                        "notes": [],
                    }
                    active_note_idx = None
                    continue

                if not current:
                    continue

                # skip range headings from being treated as details
                if RANGE_RE.match(ln):
                    # store as detail if you want, but usually it's just navigation text
                    # current["details"].append(ln)
                    continue

                # note start
                if is_note_start(ln):
                    current["notes"].append(ln)
                    active_note_idx = len(current["notes"]) - 1
                    continue

                # note continuation lines
                if active_note_idx is not None:
                    current["notes"][active_note_idx] += " " + ln
                    continue

                # normal details
                current["details"].append(ln)

    flush_current()

    with OUT_PATH.open("w", encoding="utf-8") as fout:
        for r in records:
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Done writing {len(records)} records to {OUT_PATH}")


if __name__ == "__main__":
    main()