import os
from dotenv import load_dotenv
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

load_dotenv()

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "icd10cm-2026")
API_KEY = os.getenv("PINECONE_API_KEY")
NAMESPACE = "icd10cm_2026"


def main():
    model = SentenceTransformer("all-MiniLM-L6-v2")
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