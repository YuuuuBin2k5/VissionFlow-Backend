import os
import sys
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
os.environ["VISIONFLOW_CONTROL_PLANE_URL"] = "https://visionflow-control-plane-free.onrender.com"
os.environ["VISIONFLOW_ORGANIZATION_ID"] = "7b91598c-6c3e-4e5d-8247-d3efa203984a"
os.environ["VISIONFLOW_WORKER_CLIENT_ID"] = "worker-service"
os.environ["VISIONFLOW_WORKER_CLIENT_SECRET"] = "worker-secret"
os.environ["VISIONFLOW_AUTH_AUDIENCE"] = "visionflow-control-plane"
os.environ["GEMINI_API_KEY"] = "AIzaSyCNu2LQSzyBW6ACixl1D6SLy07_vdeu0ho"
os.environ["PEXELS_API_KEY"] = "j3CIlOLR1RdRejkZPi56CCmJALu9axEyFjik0U77W3semlJtXFpMqgVp"

python_exe = sys.executable

print("=== 1. ADVANCE STUCK WORKFLOWS (GEMINI AI PLANNING & DIRECTOR) ===")
subprocess.run([python_exe, "services/control-plane/scripts/advance_stuck_workflow.py", "--all"])

print("\n=== 2. REQUEUE WORKFLOWS ===")
subprocess.run([python_exe, "services/control-plane/scripts/requeue_workflow.py", "--all"])

print("\n=== 3. RESET STUCK RENDERING ===")
subprocess.run([python_exe, "services/control-plane/scripts/reset_stuck_rendering.py", "--all"])
