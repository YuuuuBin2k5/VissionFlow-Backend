# 🧩 06. Code-Graph-RAG & MCP Server Developer Manual

## 📌 1. Overview & Architecture
`code-graph-rag` (`cgr`) là công cụ Đồ thị Tri thức Codebase RAG được tích hợp sẵn trong VisionFlow. Nó phân tích cây cú pháp AST (Tree-sitter) của toàn bộ Backend Python, lưu trữ vào **Memgraph** (Graph DB) và **Qdrant** (Vector DB), đồng thời mở cổng **MCP Server** để trợ lý AI (Google Antigravity, Claude Code, Cursor) truy vấn.

---

## 🛠️ 2. Developer Commands Cheatsheet

| Thao Tác | Lệnh Thực Thi (Powershell / CMD) |
| :--- | :--- |
| **Bật Memgraph / Qdrant Containers** | `python scripts/run_cgr.py daemon up` |
| **Đánh chỉ mục Đồ thị Protobuf** | `python scripts/run_cgr.py index --repo-path d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/VisionFlow -o d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/VisionFlow/.codegraph_proto` |
| **Quét Mã Rác (Dead Code)** | `python scripts/run_cgr.py dead-code` |
| **Chạy MCP Server stdio** | `python scripts/run_cgr.py mcp-server` |

---

## 🔌 3. MCP Server Configuration (`.mcp.json`)
Tệp `.mcp.json` tại root repository cho phép AI Assistant kết nối tự động:

```json
{
  "mcpServers": {
    "code-graph-rag": {
      "command": "d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/VisionFlow/VisionFlow_Bakend/venv/Scripts/python.exe",
      "args": [
        "-m",
        "codebase_rag.cli",
        "mcp-server"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "TARGET_REPO_PATH": "d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/VisionFlow"
      }
    }
  }
}
```
