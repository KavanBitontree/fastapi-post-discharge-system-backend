import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

from pinecone import Pinecone, ServerlessSpec

# Allow running from anywhere by adding project root to path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from icd_rag_bot.rag.openrouter_client import OpenRouterEmbedder

INDEX_NAME  = os.getenv("PINECONE_INDEX_NAME", "icd10cm-2026")
PINECONE_KEY = os.getenv("PINECONE_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

NAMESPACE   = "icd10cm_2026"
EMBED_MODEL = "openai/text-embedding-3-small"
DIMENSION   = 1536   # text-embedding-3-small output dimension
BATCH       = 64     # API call batch size

# Path relative to this script's location
IN_PATH = Path(__file__).parent.parent / "data" / "index" / "icd_records.jsonl"


def make_text(rec: dict) -> str:
    parts = [
        f"CODE: {rec.get('code', '')}",
        f"TITLE: {rec.get('title', '')}",
    ]
    details = rec.get("details") or []
    notes   = rec.get("notes") or []
    if details:
        parts.append("DETAILS: " + " | ".join(details[:30]))
    if notes:
        parts.append("NOTES: " + " | ".join(notes[:30]))
    return "\n".join(parts)


def main():
    if not PINECONE_KEY:
        raise RuntimeError("Missing PINECONE_API_KEY in .env")
    if not OPENROUTER_KEY:
        raise RuntimeError("Missing OPENROUTER_API_KEY in .env")
    if not IN_PATH.exists():
        raise RuntimeError(f"Missing data file: {IN_PATH}")

    print(f"Embedding model : {EMBED_MODEL}  (dim={DIMENSION})")
    embedder = OpenRouterEmbedder(api_key=OPENROUTER_KEY, model=EMBED_MODEL, batch_size=BATCH)

    pc = Pinecone(api_key=PINECONE_KEY)

    # Re-create index at correct dimension if needed
    existing = [idx.name for idx in pc.list_indexes()]
    if INDEX_NAME in existing:
        info = pc.describe_index(INDEX_NAME)
        current_dim = info.dimension
        if current_dim != DIMENSION:
            print(f"Index '{INDEX_NAME}' exists with dim={current_dim}; deleting and recreating for dim={DIMENSION}...")
            pc.delete_index(INDEX_NAME)
            existing = []
        else:
            print(f"Index '{INDEX_NAME}' already at dim={DIMENSION}, reusing.")

    if INDEX_NAME not in existing:
        print(f"Creating index '{INDEX_NAME}' (dim={DIMENSION}, cosine)...")
        pc.create_index(
            name=INDEX_NAME,
            dimension=DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        # Wait until ready
        import time
        for _ in range(30):
            if pc.describe_index(INDEX_NAME).status.get("ready", False):
                break
            time.sleep(3)

    index = pc.Index(INDEX_NAME)

    # Load all records
    records = []
    with IN_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"Loaded {len(records):,} records from {IN_PATH.name}")

    # Embed + upsert in batches
    upserted = 0
    for i in tqdm(range(0, len(records), BATCH), desc="Upserting ICD vectors"):
        batch_recs = records[i : i + BATCH]
        texts = [make_text(r) for r in batch_recs]

        vecs = embedder.encode(texts, normalize_embeddings=True).tolist()

        vectors = []
        for rec, vec in zip(batch_recs, vecs):
            meta = {
                "code":        rec["code"],
                "title":       rec.get("title", ""),
                "page":        int(rec.get("page", 0) or 0),
                "parent_code": rec.get("parent_code") or "",
                "level":       int(rec.get("level", 0) or 0),
            }
            vectors.append((rec["code"], vec, meta))

        index.upsert(vectors=vectors, namespace=NAMESPACE)
        upserted += len(vectors)

    print(f"\nDone. Upserted {upserted:,} vectors.")
    print(f"Index: {INDEX_NAME} | Namespace: {NAMESPACE} | Model: {EMBED_MODEL}")


if __name__ == "__main__":
    main()