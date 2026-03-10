import os
import json
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

load_dotenv()

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "icd10cm-2026")
API_KEY = os.getenv("PINECONE_API_KEY")

NAMESPACE = "icd10cm_2026"

IN_PATH = Path("data/index/icd_records.jsonl")


def make_text(rec: dict) -> str:
    # What we embed (small but informative)
    parts = [
        f"CODE: {rec.get('code', '')}",
        f"TITLE: {rec.get('title', '')}",
    ]
    details = rec.get("details") or []
    notes = rec.get("notes") or []
    if details:
        parts.append("DETAILS: " + " | ".join(details[:30]))
    if notes:
        parts.append("NOTES: " + " | ".join(notes[:30]))
    return "\n".join(parts)


def main():
    if not API_KEY:
        raise RuntimeError("Missing PINECONE_API_KEY in .env")

    if not IN_PATH.exists():
        raise RuntimeError(f"Missing {IN_PATH}. Run Step 3 first.")

    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")  # dim=384

    pc = Pinecone(api_key=API_KEY)
    index = pc.Index(INDEX_NAME)

    BATCH = 128
    batch_ids = []
    batch_vecs = []
    batch_metas = []

    total = sum(1 for _ in IN_PATH.open("r", encoding="utf-8"))

    def flush():
        nonlocal batch_ids, batch_vecs, batch_metas
        if not batch_ids:
            return
        vectors = list(zip(batch_ids, batch_vecs, batch_metas))
        index.upsert(vectors=vectors, namespace=NAMESPACE)
        batch_ids, batch_vecs, batch_metas = [], [], []

    with IN_PATH.open("r", encoding="utf-8") as f:
        for line in tqdm(f, total=total, desc="Upserting ICD vectors"):
            rec = json.loads(line)

            code = rec["code"]
            text = make_text(rec)

            vec = model.encode(text, normalize_embeddings=True).tolist()

            meta = {
                "code": code,
                "title": rec.get("title", ""),
                "page": int(rec.get("page", 0) or 0),
                "parent_code": rec.get("parent_code") or "",
                "level": int(rec.get("level", 0) or 0),
            }

            batch_ids.append(code)
            batch_vecs.append(vec)
            batch_metas.append(meta)

            if len(batch_ids) >= BATCH:
                flush()

        flush()

    print("Done upserting ICD vectors.")
    print(f"Index: {INDEX_NAME} | Namespace: {NAMESPACE}")


if __name__ == "__main__":
    main()