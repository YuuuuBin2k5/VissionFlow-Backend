"""
VisionFlow Code-Graph-RAG (cgr) Integration Helper
Unified interface for indexing, querying, and running MCP server for Code-Graph-RAG.
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

# Thêm venv site-packages nếu chưa có
BACKEND_DIR = Path(__file__).resolve().parent.parent
VENV_PYTHON = BACKEND_DIR / "venv" / "Scripts" / "python.exe"

def run_cgr_cli(args: list[str]) -> None:
    """Chạy codebase_rag CLI với môi trường được cô lập an toàn."""
    custom_env = dict(os.environ)
    custom_env["PYTHONIOENCODING"] = "utf-8"
    
    cmd = [str(VENV_PYTHON), "-m", "codebase_rag.cli"] + args
    print(f"[Code-Graph-RAG] Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=custom_env)

if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else ["--help"]
    run_cgr_cli(args)
