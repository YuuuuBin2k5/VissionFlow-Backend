"""
Query CodeGraph index.bin for Phase 4 symbols:
- ScriptPlan
- SceneNarration
- StoryPlan
- VisualIntent
- assetMatcher.ts
- opencutBridge.ts
- Scene Library repositories (source_repository, scene_repository)
- embedding/retrieval service
- existing Pexels service
- local asset library
- media storage
- rights/source metadata
- EditorPlan contracts
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from codebase_rag.graph_loader import load_graph

INDEX_PATH = "d:/VisionFlow/.codegraph/index.bin"

TARGET_SYMBOLS = [
    "ScriptPlan",
    "SceneNarration",
    "StoryPlan",
    "VisualIntent",
    "assetMatcher",
    "opencutBridge",
    "source_repository",
    "scene_repository",
    "embedding_service",
    "pexels",
    "asset_library",
    "media_storage",
    "storage_adapter",
    "rights",
    "EditorPlan",
    "ScenePlan",
    "ShotPlan",
    "SourceSceneRecord",
    "SourceAssetRecord"
]

def query_phase4():
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
        findings[sym] = matches[:20]
        print(f"Symbol '{sym}': found {len(matches)} nodes in CodeGraph.")

    out_file = Path("d:/VisionFlow/VisionFlow_Bakend/scripts/codegraph_phase4_findings.json")
    out_file.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"Saved findings to {out_file}")

if __name__ == "__main__":
    query_phase4()
