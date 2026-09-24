"""
Query CodeGraph index.bin for Phase 5 symbols:
- EditorPlan, ScenePlan, ShotPlan
- opencutBridge.ts, OpenCut timeline builder
- Edge-TTS / voice system
- modal_worker.py
- FFmpeg / ffprobe helpers
- ASS subtitle generation, caption chunking
- audio ducking, transitions
- existing render manifest
- current CreativeProposal -> OpenCut path
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# Add backend to sys.path if needed
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from codebase_rag.graph_loader import load_graph
except ImportError:
    print("codebase_rag not found in current environment.")
    sys.exit(1)

INDEX_PATH = "d:/VisionFlow/.codegraph/index.bin"
OUTPUT_PATH = BACKEND_DIR / "scripts" / "codegraph_phase5_findings.json"

TARGET_QUERIES = [
    "EditorPlan",
    "ScenePlan",
    "ShotPlan",
    "opencutBridge",
    "timeline",
    "voice_system",
    "edge_tts",
    "modal_worker",
    "ffmpeg",
    "ffprobe",
    "subtitle",
    "caption",
    "ducking",
    "transition",
    "CreativeProposal",
    "render_manifest",
    "manifest",
]

def query_phase5():
    print(f"Loading CodeGraph index from {INDEX_PATH}...")
    graph = load_graph(INDEX_PATH)
    print(f"Loaded {len(graph.nodes)} nodes, {len(graph.relationships)} relationships.")

    findings = {}

    for sym in TARGET_QUERIES:
        matches = []
        sym_lower = sym.lower()
        for node in graph.nodes:
            name = str(node.properties.get("name", ""))
            path = str(node.properties.get("path", ""))
            if sym_lower in name.lower() or sym_lower in path.lower():
                label = list(node.labels)[0] if node.labels else "Unknown"
                matches.append({
                    "id": getattr(node, "node_id", None),
                    "label": label,
                    "name": name,
                    "path": path,
                    "start_line": node.properties.get("start_line"),
                    "end_line": node.properties.get("end_line"),
                })
        # Keep top 15 most relevant matches
        findings[sym] = matches[:15]
        print(f"Found {len(matches)} matches for '{sym}'")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False)

    print(f"Report written to {OUTPUT_PATH}")

if __name__ == "__main__":
    query_phase5()
