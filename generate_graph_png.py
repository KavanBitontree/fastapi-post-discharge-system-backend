"""
generate_graph_png.py
----------------------
Generates a PNG image of the LangGraph agent topology.

Usage:
    python generate_graph_png.py

Output:
    public/graph.png

Notes:
    - Uses the Mermaid.ink API (requires internet connection).
    - DB session and patient_id are mocked — only graph structure is needed.
    - This script is for visualisation only; it does NOT start the server.
"""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent))

# Provide minimal env vars if .env is not loaded
os.environ.setdefault("GROQ_API_KEY", "placeholder")
os.environ.setdefault("DATABASE_URL", "postgresql://placeholder")

from langchain_core.runnables.graph import MermaidDrawMethod
from services.agent.graph import build_agent_graph


def main():
    output_path = Path("public") / "graph.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Building graph topology...")
    mock_db = MagicMock()
    compiled = build_agent_graph(patient_id=1, db=mock_db)

    print("Rendering PNG via Mermaid.ink API...")
    png_bytes = compiled.get_graph().draw_mermaid_png(
        draw_method=MermaidDrawMethod.API
    )

    output_path.write_bytes(png_bytes)
    print(f"Saved: {output_path.resolve()}")


if __name__ == "__main__":
    main()
