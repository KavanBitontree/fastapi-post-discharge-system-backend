import json
import re
from pathlib import Path
from tqdm import tqdm

IN_PATH = Path("data/raw/pages.jsonl")
OUT_PATH = Path("data/clean/pages_clean.jsonl")

# --- basic helpers ---
_ws_re = re.compile(r"[ \t]+")


def normalize_text(text: str) -> str:
    # Normalize whitespace
    text = text.replace("\u00a0", " ")
    text = text.replace("\r", "\n")

    # Remove repeated empty lines
    lines = [ln.rstrip() for ln in text.split("\n")]
    cleaned_lines = []
    for ln in lines:
        ln = _ws_re.sub(" ", ln).strip()
        # keep empty lines, but compress later
        cleaned_lines.append(ln)

    # Compress multiple blank lines
    out = []
    blank = 0
    for ln in cleaned_lines:
        if ln == "":
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(ln)

    return "\n".join(out).strip()


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # count lines for progress bar
    total = sum(1 for _ in IN_PATH.open("r", encoding="utf-8"))

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in tqdm(fin, total=total, desc="Cleaning pages"):
            rec = json.loads(line)
            page = rec["page"]
            text = rec.get("text", "")

            cleaned = normalize_text(text)

            fout.write(json.dumps({"page": page, "text": cleaned}, ensure_ascii=False) + "\n")

    print(f"Cleaned pages written to: {OUT_PATH}")


if __name__ == "__main__":
    main()