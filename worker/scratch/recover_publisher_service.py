import json

log_path = r"C:\Users\Admin\.gemini\antigravity\brain\1bc864e6-5ce1-4e03-82a4-5b4a9e7760e1\.system_generated\logs\transcript.jsonl"

def search():
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f):
            try:
                data = json.loads(line)
                content = str(data)
                if "publisher_service.py" in content and "publish_video_to_tiktok" in content:
                    print(f"Line {idx} matches!")
                    # Let's print keys or some summary
                    print("Type:", data.get("type"), "Status:", data.get("status"))
                    # If it's a tool output, print length
                    tool_calls = data.get("tool_calls", [])
                    print(f"Tool calls: {len(tool_calls)}")
                    tool_output = data.get("content", "")
                    if "Total Lines:" in tool_output or "class PublisherService" in tool_output:
                        print(f"Content snippet: {tool_output[:200]}...")
                        # Write to a recovery file
                        with open(f"worker/scratch/recovery_{idx}.txt", "w", encoding="utf-8") as rf:
                            rf.write(tool_output)
            except Exception as e:
                pass

if __name__ == "__main__":
    search()
