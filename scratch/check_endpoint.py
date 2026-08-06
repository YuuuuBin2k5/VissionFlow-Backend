import sys, os
sys.path.insert(0, "services/control-plane")

env_path = "services/control-plane/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

ep = os.getenv("VISIONFLOW_OBJECT_STORE_ENDPOINT", "")
bucket = os.getenv("VISIONFLOW_OBJECT_STORE_BUCKET", "")
print("ENV ENDPOINT:", ep)
print("ENV BUCKET:", bucket)

# Let's test stripping bucket from endpoint:
if ep and bucket:
    clean_ep = ep.rstrip("/")
    if clean_ep.endswith(f"/{bucket}"):
        clean_ep = clean_ep[:-len(bucket)-1]
    print("CLEAN ENDPOINT:", clean_ep)
