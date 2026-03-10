import json
from pathlib import Path
from tqdm import tqdm
import fitz  # PyMuPDF

PDF_PATH = Path("data/raw/icd.pdf")
OUT_PATH = Path("data/raw/pages.jsonl")


def get_done_pages():
    done = set()
    if OUT_PATH.exists():
        with OUT_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    done.add(int(rec["page"]))
                except Exception:
                    pass
    return done


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    done_pages = get_done_pages()

    doc = fitz.open(str(PDF_PATH))
    total = doc.page_count

    with OUT_PATH.open("a", encoding="utf-8") as out:
        for i in tqdm(range(total), desc="Extracting pages (PyMuPDF)"):
            page_num = i + 1
            if page_num in done_pages:
                continue

            page = doc.load_page(i)
            text = page.get_text("text") or ""
            text = text.replace("\u00a0", " ").strip()

            out.write(json.dumps({"page": page_num, "text": text}, ensure_ascii=False) + "\n")
            out.flush()

    print(f"Done. Wrote pages to: {OUT_PATH}")


if __name__ == "__main__":
    main()