"""
CodeGraph Comprehensive Dependency & Call Graph Audit Script
Queries the indexed CodeGraph knowledge graph (index.bin) for VisionFlow architecture.
"""

from __future__ import annotations

import json
from pathlib import Path
from codebase_rag.graph_loader import load_graph

INDEX_PATH = "d:/VisionFlow/.codegraph/index.bin"


def audit_codegraph():
    print(f"[CodeGraph] Loading graph from {INDEX_PATH}...")
    graph = load_graph(INDEX_PATH)
    print(f"[CodeGraph] Loaded {len(graph.nodes)} nodes, {len(graph.relationships)} relationships.")

    targets = [
        ("FastAPI application startup", ["app", "main.py", "FastAPI"]),
        ("Existing API/router architecture", ["ai_video", "creative_sessions", "workflows", "dubbing", "analytics", "voices"]),
        ("Database / repository layer", ["credential_repository", "db", "session", "prisma", "models"]),
        ("Workflow / orchestration hiện tại", ["WorkflowService", "CreativeSession", "intentRouter", "orchestrator"]),
        ("CreativeAgentCenter", ["CreativeAgentCenter", "CreativeProposal"]),
        ("App / Sidebar routing", ["Sidebar", "App", "ShortStudio", "OpenCutHybridStudio"]),
        ("OpenCutBridge", ["opencutBridge", "bridgeToOpenCut", "exportTimeline", "assetMatcher"]),
        ("Render worker", ["modal_worker", "start_render_worker", "local_render_daemon"]),
    ]

    report = {}

    for category, keywords in targets:
        matched_nodes = []
        for node in graph.nodes:
            name = str(node.properties.get("name", ""))
            path = str(node.properties.get("path", ""))
            label = list(node.labels)[0] if node.labels else "Unknown"
            node_id = node.node_id
            if any(kw.lower() in name.lower() or kw.lower() in path.lower() for kw in keywords):
                # Get outgoing and incoming relationships
                outgoing = graph.get_outgoing_relationships(node_id)
                incoming = graph.get_incoming_relationships(node_id)
                
                out_repr = []
                for r in outgoing:
                    if r.type in ["CALLS", "IMPORTS", "INSTANTIATES", "DEPENDS_ON", "DEFINES"]:
                        target = graph.get_node_by_id(r.to_id)
                        t_name = target.properties.get("name") if target else r.to_id
                        out_repr.append(f"{r.type} -> {t_name}")

                in_repr = []
                for r in incoming:
                    if r.type in ["CALLS", "IMPORTS", "INSTANTIATES"]:
                        source = graph.get_node_by_id(r.from_id)
                        s_name = source.properties.get("name") if source else r.from_id
                        in_repr.append(f"{r.type} <- {s_name}")

                matched_nodes.append({
                    "id": node_id,
                    "label": label,
                    "name": name,
                    "path": path,
                    "outgoing_calls": out_repr[:8],
                    "incoming_callers": in_repr[:8],
                })
        report[category] = matched_nodes[:10]

    output_path = "d:/VisionFlow/VisionFlow_Bakend/scripts/codegraph_audit_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"[CodeGraph] Audit complete. Written {len(report)} categories to {output_path}")


if __name__ == "__main__":
    audit_codegraph()
