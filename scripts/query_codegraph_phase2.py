"""
Query CodeGraph index.bin for Phase 2 Source Intelligence Foundation symbols.
Searches for:
1. Media download utilities
2. Storage adapters (Cloudflare R2 / S3)
3. Temp media handling
4. ffprobe utilities
5. FFmpeg wrappers
6. Faster-Whisper / transcription
7. Scene splitting logic
8. assetMatcher
9. Pexels services
10. Existing database / repository architecture
11. OpenCut asset contracts
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from codebase_rag.graph_loader import load_graph

INDEX_PATH = "d:/VisionFlow/.codegraph/index.bin"

PHASE2_TARGETS = {
    "media_download": ["download", "download_media", "downloader", "ytdl", "yt_dlp", "douyin", "tiktok", "fetch_media"],
    "storage_r2_s3": ["r2", "s3", "storage", "visionflow_object_storage", "upload", "presigned", "boto3"],
    "temp_media": ["temp", "tmp", "tempfile", "temp_dir", "cleanup", "media_dir", "cache_dir"],
    "ffprobe": ["ffprobe", "probe", "get_duration", "video_info", "media_info", "probe_audio"],
    "ffmpeg": ["ffmpeg", "convert", "transcode", "extract_audio", "extract_frames", "extract_keyframes"],
    "transcription": ["whisper", "faster_whisper", "transcribe", "speech_to_text", "stt", "asr"],
    "scene_splitting": ["scene", "split", "scenedetect", "detect_scenes", "shot", "boundaries"],
    "asset_matcher": ["assetMatcher", "asset_matcher", "match_assets", "similarity", "match_scene"],
    "pexels": ["pexels", "stock", "stock_video", "search_pexels"],
    "db_repository": ["repository", "session", "alembic", "database", "crud", "models", "Base"],
    "opencut_contracts": ["opencut", "timeline", "composition", "shotPlan", "assetPlan", "track"]
}

def query_phase2():
    print(f"Loading CodeGraph index from {INDEX_PATH}...")
    graph = load_graph(INDEX_PATH)
    print(f"Loaded {len(graph.nodes)} nodes, {len(graph.relationships)} relationships.")

    results = {}

    for category, keywords in PHASE2_TARGETS.items():
        matches = []
        for node in graph.nodes:
            name = str(node.properties.get("name", ""))
            path = str(node.properties.get("path", ""))
            label = list(node.labels)[0] if node.labels else "Unknown"
            
            # Check if any keyword matches
            matched_kw = [kw for kw in keywords if kw.lower() in name.lower() or kw.lower() in path.lower()]
            if matched_kw:
                matches.append({
                    "id": node.node_id,
                    "label": label,
                    "name": name,
                    "path": path,
                    "matched_keywords": matched_kw
                })
        results[category] = matches[:15] # Top 15 matches per category

    output_path = Path("d:/VisionFlow/VisionFlow_Bakend/scripts/codegraph_phase2_findings.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Saved CodeGraph Phase 2 findings to {output_path}")
    for cat, items in results.items():
        print(f"\n--- {cat} ({len(items)} matches) ---")
        for item in items[:5]:
            print(f"  [{item['label']}] {item['name']} ({item['path']})")

if __name__ == "__main__":
    query_phase2()
