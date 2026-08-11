# 🏗️ 02. Backend Component Architecture & Pipeline Sequence Specs

## 🏛️ 1. Detailed Component Architecture Diagram

```mermaid
graph TD
    Client["React TSX Client / Telegram Bot"] -->|REST API / JWT| FastAPI["FastAPI Control Plane (Port 8000)"]
    FastAPI -->|Prisma / SQLAlchemy| DB[("Neon PostgreSQL DB")]
    
    subgraph "Asynchronous Render Worker System"
        WorkerDaemon["Render Worker Daemon (start_render_worker.py)"]
        DouyinExtractor["Douyin Client (Playwright Stealth)"]
        WhisperEngine["Lyric Transcription (Faster-Whisper)"]
        LLMTranslator["LLM Service (Gemini Multi-Key Vault)"]
        TTSService["TTS Engine (Edge-TTS / Azure / ElevenLabs)"]
        SubtitleRenderer["Smart Text Detector (ASS Kinetic Render)"]
        FFmpegComposer["Clip Composer (FFmpeg Multi-Layer)"]
    end
    
    WorkerDaemon -->|Poll Job PENDING| DB
    WorkerDaemon --> DouyinExtractor
    WorkerDaemon --> WhisperEngine
    WorkerDaemon --> LLMTranslator
    WorkerDaemon --> TTSService
    WorkerDaemon --> SubtitleRenderer
    WorkerDaemon --> FFmpegComposer
    
    FFmpegComposer -->|Upload Video| R2[("Cloudflare R2 Object Store")]
    FFmpegComposer -->|Update COMPLETED| DB
    
    subgraph "Publisher Service"
        PublisherWorker["Publisher Worker (services/publisher-worker)"]
        YouTubeAPI["YouTube Data API v3"]
        TikTokAPI["TikTok Open API"]
    end
    
    DB -->|Trigger Publish| PublisherWorker
    PublisherWorker --> YouTubeAPI
    PublisherWorker --> TikTokAPI
```

---

## ⏱️ 2. UML Sequence Diagram: Job Execution Sequence (B1 ➔ B7)

```mermaid
sequenceDiagram
    autonumber
    participant C as Client / Bot
    participant CP as Control Plane API
    participant DB as Neon PostgreSQL
    participant W as Render Worker Daemon
    participant DY as Douyin Client
    participant LLM as Gemini Vault
    participant FF as FFmpeg Engine
    participant R2 as Cloudflare R2

    C->>CP: POST /api/v1/jobs (Create Render Job)
    CP->>DB: INSERT INTO video_pipeline_jobs (status = 'PENDING')
    CP-->>C: 201 Created {job_id: "UUIDv4"}
    
    loop Continuous Worker Polling Loop
        W->>DB: SELECT * FROM video_pipeline_jobs WHERE status = 'PENDING' LIMIT 1
        DB-->>W: Return Pending Job
    end
    
    W->>DB: UPDATE video_pipeline_jobs SET status = 'PROCESSING'
    
    rect rgb(240, 248, 255)
        Note over W,DY: B1: Douyin CDN Extraction
        W->>DY: download_video_with_ytdlp(url, output_dir="D:/temp")
        DY-->>W: Return raw_video.mp4 path
    end
    
    rect rgb(255, 250, 240)
        Note over W,LLM: B2-B3: Transcribe & Gemini Translation
        W->>W: Faster-Whisper Transcribe audio
        W->>LLM: translate_timeline(batches, target_lang="vi")
        LLM-->>W: Return translated & character-assigned timeline
    end
    
    rect rgb(240, 255, 240)
        Note over W,FF: B4-B6: TTS Dubbing, ASS Subtitle & FFmpeg Overlay
        W->>W: Synthesize Edge-TTS audio segments
        W->>W: Generate kinetic_subtitles.ass (72px, outline 4)
        W->>FF: Execute FFmpeg multi-layer muxing & audio ducking
        FF-->>W: Return final_output_1080x1920.mp4
    end
    
    rect rgb(255, 240, 245)
        Note over W,R2: B7: Cloudflare R2 Upload & Completion
        W->>R2: upload_file(final_output.mp4)
        R2-->>W: Return public CDN R2 URL
        W->>DB: UPDATE video_pipeline_jobs SET status = 'COMPLETED', output_url = CDN_URL
    end
```

---

## 🛠️ 3. Pipeline Error Handling & Recovery Matrix

| Điểm Phát Sinh Lỗi | Nguyên Nhân Gốc | Giải Pháp Xử Lý Tự Động Trong Code |
| :--- | :--- | :--- |
| **Douyin Extract Fail** | CDN URL dính IP Rate Limit hoặc CAPTCHA | Chuyển sang Playwright Stealth headless browser giả lập hành vi người dùng, ép ghi ổ đĩa D:. |
| **Gemini API 429** | API Key hết Quota / Overused | `LLMService._get_gemini_keys()` giải mã và xoay sang Key dự phòng kế tiếp trong Postgres Vault. |
| **FFmpeg Filter Error** | Bản build FFmpeg không hỗ trợ `force_style` | `check_subtitles_supports_force_style()` kiểm tra động lệnh help, tự động cắt tỉa tham số `force_style` nếu không hỗ trợ. |
| **Drive C: Space Full** | Temp file của yt-dlp & Playwright phồng to | Ép toàn bộ biến `TEMP`, `TMP`, `TMPDIR` và `--paths temp:...` ghi trực tiếp sang **Ổ đĩa D:**. |
