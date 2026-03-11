import json
import sqlite3
from pathlib import Path
from tqdm import tqdm

IN_PATH = Path("data/index/icd_records.jsonl")
DB_PATH = Path("data/index/icd_fts.sqlite")


def richness_score(title: str, details: str, notes: str) -> int:
    # simple "more text = better"
    return len(title) + len(details) + len(notes)


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE icd (
        code TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        details TEXT,
        notes TEXT,
        page INTEGER,
        parent_code TEXT,
        level INTEGER,
        score INTEGER DEFAULT 0
    );
    """)

    # We'll create FTS as an "external content" index
    cur.execute("""
    CREATE VIRTUAL TABLE icd_fts USING fts5(
        code,
        title,
        body
    );
    """)

    cur.execute("CREATE INDEX idx_icd_parent ON icd(parent_code);")
    cur.execute("CREATE INDEX idx_icd_level ON icd(level);")

    total = sum(1 for _ in IN_PATH.open("r", encoding="utf-8"))

    with IN_PATH.open("r", encoding="utf-8") as f:
        for line in tqdm(f, total=total, desc="Loading records into SQLite"):
            rec = json.loads(line)

            code = rec["code"]
            title = rec.get("title", "") or ""
            details_list = rec.get("details", []) or []
            notes_list = rec.get("notes", []) or []
            page = rec.get("page", None)
            parent = rec.get("parent_code", None)
            level = rec.get("level", None)

            details = "\n".join(details_list).strip()
            notes = "\n".join(notes_list).strip()

            score = richness_score(title, details, notes)

            # If code already exists, only replace if this one is richer
            cur.execute("SELECT score FROM icd WHERE code = ?", (code,))
            row = cur.fetchone()

            if row is None:
                cur.execute(
                    "INSERT INTO icd(code,title,details,notes,page,parent_code,level,score) VALUES (?,?,?,?,?,?,?,?)",
                    (code, title, details, notes, page, parent, level, score),
                )
            else:
                existing_score = row[0] or 0
                if score > existing_score:
                    cur.execute(
                        """UPDATE icd
                           SET title=?, details=?, notes=?, page=?, parent_code=?, level=?, score=?
                           WHERE code=?""",
                        (title, details, notes, page, parent, level, score, code),
                    )

    conn.commit()

    # Now (re)build FTS from final icd table
    cur.execute("DELETE FROM icd_fts;")
    cur.execute("""
        INSERT INTO icd_fts(code, title, body)
        SELECT
            code,
            title,
            trim(coalesce(title,'') || ' ' || coalesce(details,'') || ' ' || coalesce(notes,''))
        FROM icd;
    """)
    conn.commit()

    conn.close()
    print(f"Built FTS DB at: {DB_PATH}")


if __name__ == "__main__":
    main()