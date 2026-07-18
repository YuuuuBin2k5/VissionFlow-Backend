import json

log_path = r"C:\Users\Admin\.gemini\antigravity\brain\1bc864e6-5ce1-4e03-82a4-5b4a9e7760e1\.system_generated\logs\transcript.jsonl"

def recover():
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f):
            if idx == 648:
                data = json.loads(line)
                # The tool output is in the 'content' field
                content = data.get("content", "")
                with open("worker/scratch/recovered_full_648.txt", "w", encoding="utf-8") as out:
                    out.write(content)
                print(f"Recovered full content from step 648! Length: {len(content)}")
                
            if idx == 699:
                data = json.loads(line)
                content = data.get("content", "")
                with open("worker/scratch/recovered_full_699.txt", "w", encoding="utf-8") as out:
                    out.write(content)
                print(f"Recovered full content from step 699! Length: {len(content)}")

if __name__ == "__main__":
    recover()
