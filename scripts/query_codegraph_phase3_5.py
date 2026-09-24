"""
Query CodeGraph index.bin for Phase 3.5 symbols:
- research_service.py
- story_planner.py
- script_service.py
- script_quality_gate.py
- orchestrator.py
- production_controller.py
- AutoVideoComposer
- productionApi
- contracts.py
- embedding_service.py
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from codebase_rag.graph_loader import load_graph

INDEX_PATH = "d:/VisionFlow/.codegraph/index.bin"

TARGET_SYMBOLS = [
    "research_service",
    "story_planner",
    "script_service",
    "script_quality_gate",
    "orchestrator",
    "production_controller",
    "AutoVideoComposer",
    "productionApi",
    "contracts",
    "embedding_service",
    "shortContracts",
    "longContracts",
    "creativeSession",
]

def query_phase3_5():
    print(f"Loading CodeGraph index from {INDEX_PATH}...")
    graph = load_graph(INDEX_PATH)
    print(f"Loaded {len(graph.nodes)} nodes, {len(graph.relationships)} relationships.")

    findings = {}

    for sym in TARGET_SYMBOLS:
        matches = []
        for node in graph.nodes:
            name = str(node.properties.get("name", ""))
            path = str(node.properties.get("path", ""))
            label = list(node.labels)[0] if node.labels else "Unknown"

            if sym.lower() in name.lower() or sym.lower() in path.lower():
                matches.append({
                    "id": node.node_id,
                    "label": label,
                    "name": name,
                    "path": path,
                })
        findings[sym] = matches[:15] # Top 15 matches per symbol
        print(f"Symbol '{sym}': found {len(matches)} nodes in CodeGraph.")

    out_file = Path("d:/VisionFlow/VisionFlow_Bakend/scripts/codegraph_phase3_5_findings.json")
    out_file.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"Saved findings to {out_file}")

if __name__ == "__main__":
    query_phase3_5()
