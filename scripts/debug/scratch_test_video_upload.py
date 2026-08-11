import requests

# Test uploading export.mp4 to tmpfiles.org
file_path = "worker/workspace_temp/visionflow/aa9bf4b5-977d-43f3-a982-12405d39b00f/export.mp4"

print(f"Uploading {file_path} to tmpfiles.org...")
with open(file_path, "rb") as f:
    resp = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f})

print(f"Status Code: {resp.status_code}")
data = resp.json()
print(data)

if data.get("status") == "success":
    url = data["data"]["url"]
    # Convert view URL to direct download URL: https://tmpfiles.org/12345/export.mp4 -> https://tmpfiles.org/dl/12345/export.mp4
    direct_url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    print(f"\n🎉 Direct Playable Video URL: {direct_url}")
