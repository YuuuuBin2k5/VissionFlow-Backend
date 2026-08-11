"""
1-Click Local Render Runner for VisionFlow
Runs the render worker directly on your machine without needing GitHub Actions.
"""

import os
import sys
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Environment configuration
os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["VISIONFLOW_CONTROL_PLANE_URL"] = "https://visionflow-control-plane-free.onrender.com"
os.environ["VISIONFLOW_ORGANIZATION_ID"] = "7b91598c-6c3e-4e5d-8247-d3efa203984a"
os.environ["VISIONFLOW_WORKER_CLIENT_ID"] = "worker-service"
os.environ["VISIONFLOW_WORKER_CLIENT_SECRET"] = "worker-secret"
os.environ["VISIONFLOW_AUTH_AUDIENCE"] = "visionflow-control-plane"

print("=======================================================")
print("[VisionFlow] 1-CLICK LOCAL RENDER WORKER")
print("=======================================================")

# Step 1: Advance stuck planning workflows
print("\n[Step 1/2] Advancing stuck planning workflows...")
advance_script = os.path.join("services", "control-plane", "scripts", "advance_stuck_workflow.py")
if os.path.exists(advance_script):
    subprocess.run([sys.executable, advance_script, "--all"], check=False)

# Step 2: Reset any stuck rendering workflows in DB
print("\n[Step 2/2] Resetting stuck rendering workflows...")
reset_script = os.path.join("services", "control-plane", "scripts", "reset_stuck_rendering.py")
if os.path.exists(reset_script):
    subprocess.run([sys.executable, reset_script, "--all"], check=False)

print("\n✅ Local workflow check & reset finished!")
