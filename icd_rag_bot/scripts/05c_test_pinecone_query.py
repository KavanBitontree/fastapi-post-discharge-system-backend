import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from pinecone import Pinecone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from icd_rag_bot.rag.openrouter_client import OpenRouterEmbedder

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "icd10cm-2026")
API_KEY = os.getenv("PINECONE_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
NAMESPACE = "icd10cm_2026"


def main():
    model = OpenRouterEmbedder(api_key=OPENROUTER_KEY, model="openai/text-embedding-3-small")
    pc = Pinecone(api_key=API_KEY)
    index = pc.Index(INDEX_NAME)

    queries = [
        "cholera",
        "hunchback neck spine kyphosis",
        "cancer of urethra",
        "sugar disease type 2",
    ]

    for q in queries:
        qvec = model.encode(q, normalize_embeddings=True).tolist()
        res = index.query(vector=qvec, top_k=5, include_metadata=True, namespace=NAMESPACE)

        print("\n=== QUERY:", q, "===")
        for m in res["matches"]:
            md = m["metadata"]
            print(m["id"], round(m["score"], 4), md.get("title"), "page:", md.get("page"))


if __name__ == "__main__":
    main()