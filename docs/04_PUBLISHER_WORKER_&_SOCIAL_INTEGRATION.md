# 📢 04. Publisher Worker & Multi-Platform Social Media Integration

## 📌 1. Architecture Overview
`publisher-worker` (`services/publisher-worker/`) là microservice nền chịu trách nhiệm tự động đăng tải video hoàn chỉnh sau bước B7 lên các nền tảng mạng xã hội: **YouTube Shorts**, **TikTok**, và **Facebook Reels**.

---

## 🔄 2. OAuth Token Lifecycle & Auto-Refresh Sequence

```mermaid
sequenceDiagram
    autonumber
    participant PW as Publisher Worker
    participant DB as Neon PostgreSQL
    participant Auth as Platform OAuth Server (Google / TikTok)
    participant API as YouTube Data API / TikTok API

    PW->>DB: Fetch PENDING Publish Tasks
    DB-->>PW: Return Task + Target Refresh Token
    
    alt Token Expired (expires_at < NOW)
        PW->>Auth: POST /oauth/v2/token (Grant: refresh_token)
        Auth-->>PW: 200 OK {access_token: "new_at", expires_in: 3600}
        PW->>DB: UPDATE publish_targets SET access_token = "new_at"
    end
    
    PW->>API: POST /upload (Video Stream + Metadata)
    API-->>PW: 201 Created {video_id: "yt_12345"}
    PW->>DB: UPDATE publish_tasks SET status = 'PUBLISHED', external_id = "yt_12345"
```

---

## 🛠️ 3. Metadata Generation & Hashtags Injection
Publisher Worker tự động định dạng tiêu đề, mô tả và hashtags tối ưu SEO:
- **Title Optimization**: Giới hạn tối đa 100 ký tự (YouTube) / 2200 ký tự (TikTok).
- **Auto Hashtags**: Tự động chèn các hashtag xu hướng (`#Shorts`, `#Reels`, `#TikTokTrending`, `#VisionFlowAI`).
- **Privacy Status**: Hỗ trợ chế độ `public`, `unlisted`, hoặc `private`.
