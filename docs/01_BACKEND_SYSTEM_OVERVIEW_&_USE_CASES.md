# 🌐 01. Backend System Overview & Pro Developer Use-Case Specification

## 📌 1. Executive Summary & Core Value Proposition
**VisionFlow Backend Core** là hệ thống Microservices & Asynchronous Worker Pipeline chịu trách nhiệm tự động hóa việc bóc tách, biên dịch, lồng tiếng và sản xuất video ngắn chất lượng cao (Shorts / Reels / TikTok).

Hệ thống được thiết kế theo kiến trúc **Distributed Multi-Tenant Monorepo**, phục vụ các tính năng:
- **Douyin/TikTok Bóc Tách Watermark**: Khai thác Playwright Stealth để bóc tách link CDN video gốc.
- **Whisper & AI Translation Engine**: Chép thoại đa ngôn ngữ và dịch thuật ngữ cảnh bằng Gemini AI.
- **Multi-Engine TTS & Audio Mastering**: Hỗ trợ Edge-TTS, Azure Speech, ElevenLabs, Gemini TTS kèm nén tốc độ đọc (atempo) và trộn âm BGM.
- **Kinetic Subtitle Renderer**: Rendering phụ đề nổi `.ass` chuẩn 72px với hiệu ứng viền bóng nổi 3D.
- **Cloudflare R2 Object Store & Auto Publisher**: Tải lưu trữ S3 và tự động đăng tải video lên YouTube Shorts, TikTok, Facebook Reels.

---

## 📐 2. UML Use Case Diagram (Sơ Đồ Use Case Tổng Thể)

```mermaid
usecaseDiagram
    actor Developer as "Developer / Admin"
    actor Creator as "Creator User"
    actor TelegramBot as "Telegram Orchestrator"
    actor Worker as "Render Worker Daemon"

    package "VisionFlow Backend Subsystem" {
        usecase UC1 as "UC-01: Authenticate & OAuth Refresh"
        usecase UC2 as "UC-02: Create Video Rendering Job"
        usecase UC3 as "UC-03: Process B1-B7 Video Pipeline"
        usecase UC4 as "UC-04: Manage Multi-Key Credentials Vault"
        usecase UC5 as "UC-05: Inspect Media & Cloudflare R2 Upload"
        usecase UC6 as "UC-06: Auto-Publish to YouTube/TikTok"
        usecase UC7 as "UC-07: Query CodeGraph AST & MCP Metrics"
    }

    Creator --> UC1
    Creator --> UC2
    TelegramBot --> UC2
    
    UC2 .> UC3 : <<include>>
    UC3 --> Worker
    Worker --> UC4
    Worker --> UC5
    
    UC5 .> UC6 : <<trigger>>
    Developer --> UC7
```

---

## 📑 3. Specifications UC-01 ➔ UC-06 (Chi Tiết Nghiệp Vụ)

### UC-02: Create Video Rendering Job
- **Primary Actor**: Creator User / Telegram Orchestrator.
- **Pre-conditions**: Người dùng đã được xác thực JWT token có role `CREATOR` hoặc `ADMIN`.
- **Input Parameters**:
  - `input_url`: Đường dẫn Douyin/TikTok video gốc.
  - `target_language`: Ngôn ngữ đích (`vi`, `en`, `ja`, `zh`).
  - `voice_id`: ID giọng đọc AI chỉ định (`vi-VN-NamMinhNeural`, `vi-VN-HoaiMyNeural`).
  - `subtitle_style`: Cấu hình style phụ đề (`NeonKinetic`, `ClassicWhite`).
- **Main Success Scenario**:
  1. Client gửi POST `/api/v1/jobs` với Payload hợp lệ.
  2. Control Plane kiểm tra quota và lưu record `video_pipeline_jobs` trạng thái `PENDING`.
  3. Continuous Worker Daemon phát hiện job mới và đổi trạng thái sang `PROCESSING`.
  4. Trả về `job_id` dạng UUIDv4 cho Client theo dõi qua WebSocket/Polling.

### UC-03: Process B1-B7 Video Pipeline
- **Actor**: Continuous Render Worker (`python start_render_worker.py --loop`).
- **Flow Details**:
  - **B1 (Ingest)**: Playwright Stealth lấy CDN URL gốc không logo.
  - **B2 (Transcribe)**: Faster-Whisper trích xuất âm thanh và thời mốc microsecond.
  - **B3 (Translate & Phân vai)**: Gemini LLM dịch thuật gối đầu bối cảnh (Batching 40 lines).
  - **B4 (TTS Dubbing)**: Edge-TTS / Azure TTS sinh file `.mp3`, nén tốc độ `atempo`.
  - **B5 (ASS Subtitles)**: Sinh file `.ass` kinetic typography 72px.
  - **B6 (FFmpeg Layering)**: Trộn video, audio lồng tiếng, BGM và burn-in subtitle.
  - **B7 (R2 & DB Sync)**: Push video 1080x1920 lên Cloudflare R2 Bucket, cập nhật `COMPLETED`.
