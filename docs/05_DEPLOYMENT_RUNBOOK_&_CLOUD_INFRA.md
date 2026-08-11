# 🚀 05. Production Deployment Runbook & Cloud Infrastructure Spec

## ☁️ 1. Infrastructure Topography

```
+-----------------------------------------------------------------------+
|                            RENDER.COM CLOUD                           |
|                                                                       |
|  +--------------------------------+  +-------------------------------+  |
|  | FastAPI Control Plane          |  | Publisher Worker Service      |  |
|  | Web Service (Python 3.11)      |  | Background Worker             |  |
|  +---------------+----------------+  +---------------+---------------+  |
+------------------|-----------------------------------|----------------+
                   |                                   |
                   v                                   v
+------------------+-----------------------------------+----------------+
|                         NEON POSTGRESQL (CLOUD)                       |
+------------------+----------------------------------------------------+
                   ^
                   |
+------------------+----------------------------------------------------+
|                      LOCAL / ON-PREMISE RENDER WORKER                 |
|  - Continuous Render Worker Daemon (python start_render_worker.py)    |
|  - FFmpeg v7.1 GPU Acceleration + Drive D: Storage                    |
+-----------------------------------------------------------------------+
```

---

## 🛠️ 2. Step-by-Step Production Deployment Runbook

### Step 1: Clone & Configure Virtualenv
```powershell
cd VisionFlow_Bakend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 2: Set Environment Variables (`.env`)
```ini
DATABASE_URL="postgresql://neondb_owner:...@ep-cool-name.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY="7c82c3c7ef23758b9ea79dfa58f4a3e3c66baea5c704f47bb920b7efcfce38b4"
VISIONFLOW_OBJECT_STORE_ENDPOINT="https://ec302240fdb8cad9...cloudflare.com"
VISIONFLOW_OBJECT_STORE_BUCKET="vision-flow"
VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID="fd28f47a855e5f2097d5f8c24c50da70"
VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY="c329293210d831c0bdba01f2...a73f9b67819b7c3069cc9c6"
```

### Step 3: Run Database Migrations
```powershell
npx prisma db push
```

### Step 4: Start Continuous Render Worker Daemon
```powershell
python start_render_worker.py --loop
```

---

## 🔄 3. Continuous Integration & Deployment (GitHub Actions)
Tệp `.github/workflows/production-deploy.yml` tự động thực thi khi push lên nhánh `main`:
1. Execute Pytest unit test suite.
2. Verify Python imports & types (`mypy`).
3. Deploy Control Plane to Render.com Webhook.
4. Auto-sync `main` branch to `production` branch.
