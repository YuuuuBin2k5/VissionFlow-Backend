# 🗄️ 03. Database Data Models & Fernet Credential Vault Spec

## 📊 1. ERD (Entity Relationship Diagram)

```mermaid
erDiagram
    ORGANIZATION ||--o{ USER : contains
    ORGANIZATION ||--o{ VIDEO_PIPELINE_JOB : owns
    ORGANIZATION ||--o{ PROVIDER_CREDENTIAL : maintains
    ORGANIZATION ||--o{ PUBLISH_TARGET : configures

    USER {
        uuid id PK
        string email
        string password_hash
        string role
        uuid organization_id FK
        timestamp created_at
    }

    ORGANIZATION {
        uuid id PK
        string name
        string plan_tier
        timestamp created_at
    }

    VIDEO_PIPELINE_JOB {
        uuid id PK
        string status
        string input_url
        string output_url
        jsonb render_settings
        uuid organization_id FK
        timestamp created_at
        timestamp updated_at
    }

    PROVIDER_CREDENTIAL {
        uuid id PK
        string provider_name
        text encrypted_credentials
        boolean is_active
        uuid organization_id FK
        timestamp updated_at
    }

    PUBLISH_TARGET {
        uuid id PK
        string platform
        text access_token
        text refresh_token
        timestamp expires_at
        uuid organization_id FK
    }
```

---

## 🔒 2. Multi-Key Vault Encryption Specification

Tất cả thông tin nhạy cảm của người dùng (API Keys Gemini, Pexels, ElevenLabs, OAuth Tokens) được mã hóa ở cấp ứng dụng (Application-Level Encryption):

```python
# Sơ đồ mã hóa Fernet Vault trong Backend
hash_material = hashlib.sha256(VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY.encode()).digest()
fernet_key = base64.urlsafe_b64encode(hash_material)
cipher = Fernet(fernet_key)

# Giải mã API key trong Worker
raw_json = cipher.decrypt(credential_record.encrypted_credentials.encode()).decode()
keys = json.loads(raw_json)
```

---

## 📑 3. Fast Indexing Strategy
- **Index `idx_jobs_status_org`**: Index phức hợp `(status, organization_id, created_at)` trên bảng `video_pipeline_jobs` giúp Worker Daemon poll job mới với thời gian phản hồi `< 2ms`.
- **Index `idx_credentials_active`**: Index `(provider_name, is_active)` giúp tải danh sách keys xoay vòng tức thì.
