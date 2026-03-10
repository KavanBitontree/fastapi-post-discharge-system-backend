import os
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "icd10cm-2026")
API_KEY = os.getenv("PINECONE_API_KEY")

DIMENSION = 384   # for all-MiniLM-L6-v2
METRIC = "cosine"


def main():
    if not API_KEY:
        raise RuntimeError("Missing PINECONE_API_KEY in .env")

    pc = Pinecone(api_key=API_KEY)

    existing = [i["name"] for i in pc.list_indexes()]
    if INDEX_NAME in existing:
        print(f"✅ Index already exists: {INDEX_NAME}")
        return

    pc.create_index(
        name=INDEX_NAME,
        dimension=DIMENSION,
        metric=METRIC,
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )

    print(f"Created Pinecone index: {INDEX_NAME}")


if __name__ == "__main__":
    main()