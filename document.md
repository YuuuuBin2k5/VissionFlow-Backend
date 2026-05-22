TÀI LIỆU ĐẶC TẢ HỆ THỐNG: CHAT-DRIVEN TIKTOK AUTOMATION TOOL (AGENT-READABLE)I. KIẾN TRÚC TỔNG THỂ & PHÂN CHIA MODULE (SYSTEM TOPOLOGY)Hệ thống được thiết kế theo kiến trúc Hướng sự kiện phi tập trung (Decoupled Event-Driven) chia làm 3 tầng độc lập để tối ưu hóa hiệu năng, tránh nghẽn luồng xử lý đồ họa (Media Rendering CPU Spikes).[ Giao diện Chat Telegram ] 
            │ (Webhook / Polling)
            ▼
┌────────────────────────────────────────────────────────┐
│ TẦNG 1: ORCHESTRATOR ENGINE (Node.js / NestJS)          │
│ - Tiếp nhận webhook, phân tích cú pháp lệnh            │
│ - Quản lý State Machine trong cơ sở dữ liệu MySQL      │
│ - Phân phối tác vụ vào Hàng đợi Redis (BullMQ)         │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ [Redis Queue - Job Packet]
┌────────────────────────────────────────────────────────┐
│ TẦNG 2: CORE MEDIA WORKER (Python 3.10+)                │
│ - Luồng AI Agent (CrewAI/LangChain) xử lý chuỗi Prompt │
│ - Engine chuyển đổi Text-to-Speech (Edge-TTS)          │
│ - Bộ xử lý đồ họa, ghép nối video (MoviePy Core)        │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ [Đăng bài hoặc Gửi duyệt duyệt]
┌────────────────────────────────────────────────────────┐
│ TẦNG 3: STEALTH PUBLISHING AGENT (Playwright Engine)    │
│ - Tự động hóa trình duyệt chống phát hiện (Stealth)    │
│ - Nạp Session Cookie, Đăng tải trực tiếp TikTok Studio │
└────────────────────────────────────────────────────────┘
II. THIẾT KẾ CƠ SỞ DỮ LIỆU ĐỒNG BỘ TRẠNG THÁI (MYSQL SCHEMA)AI Agent cần khởi tạo cấu trúc bảng dữ liệu với ràng buộc chặt chẽ để theo dõi vòng đời của từng video. Hệ thống sử dụng cú pháp MySQL chuẩn.SQLCREATE DATABASE IF NOT EXISTS tiktok_agent_automation_db;
USE tiktok_agent_automation_db;

-- 1. Bảng lưu trữ chiến dịch kích hoạt từ ô chat
CREATE TABLE channels_campaign (
    id INT AUTO_INCREMENT PRIMARY KEY,
    telegram_chat_id BIGINT NOT NULL,
    topic VARCHAR(255) NOT NULL,
    target_audience TEXT,
    status VARCHAR(50) DEFAULT 'INITIALIZING', -- INITIALIZING, RUNNING, PAUSED, ENDED
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Bảng quản lý trạng thái chi tiết của chuỗi video 30 ngày
CREATE TABLE video_pipeline_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    campaign_id INT,
    day_number INT NOT NULL,
    scheduled_post_time DATETIME NOT NULL,
    
    -- Dữ liệu cấu trúc sinh ra bởi LLM
    video_title_idea VARCHAR(255),
    hook_text_3s TEXT,
    full_voice_script TEXT,
    scenes_layout_json LONGTEXT,     -- Cấu trúc phân cảnh hình ảnh và text overlay
    seo_tags_metadata JSON,          -- Tiêu đề, hashtag tối ưu tăng trưởng
    
    -- Dữ liệu Media đầu ra
    audio_file_path VARCHAR(500),
    video_output_path VARCHAR(500),
    
    -- Trạng thái điều phối dòng việc (State Machine)
    pipeline_state VARCHAR(50) DEFAULT 'QUEUED', 
    -- Các trạng thái: QUEUED -> AI_PARSED -> AUDIO_COMPOSED -> ASSETS_READY -> RENDERED -> USER_APPROVED -> PUBLISHED
    
    retry_count INT DEFAULT 0,
    error_log_trace TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES channels_campaign(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Bảng Log thời gian thực phục vụ việc hiển thị tiến độ qua ô chat
CREATE TABLE process_realtime_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    job_id INT,
    execution_step VARCHAR(100), -- e.g., LLM_WORK, AUDIO_SYNTH, VIDEO_EDIT, UPLOAD_ENGINE
    status_level VARCHAR(20),     -- INFO, WARN, ERROR
    log_message TEXT,
    logged_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES video_pipeline_jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
III. MA TRẬN LỆNH CHAT BOT (TELEGRAM CONTROL INTERFACE)Tầng Orchestrator bắt buộc phải triển khai bộ phân tích cú pháp tin nhắn (Message Parser) để chuyển đổi văn bản chat thành các bản ghi điều phối trong cơ sở dữ liệu.Cú pháp Lệnh (Command)Tham số đầu vàoXử lý logic của Hệ thốngPhản hồi của Bot (Response)/start_campaign[Chủ đề] | [Đối tượng]Tạo bản ghi mới trong channels_campaign. Kích hoạt chuỗi Job 30 ngày vào trạng thái QUEUED và gửi Task tổng vào Redis."🚀 Đã khởi tạo chiến dịch thành công. Đang tiến hành lập lịch và phân tích nội dung..."/statusKhôngTruy vấn số lượng Job theo trạng thái trong video_pipeline_jobs."📊 Tiến độ kênh: Đã đăng: 5/30 | Đang xử lý: 1 | Lỗi cần kiểm tra: 0."/preview [job_id]job_idLấy đường dẫn file video_output_path gửi trực tiếp file .mp4 lên ô chat để người dùng kiểm duyệt visual.Gửi tệp đính kèm Video kèm nút bấm tương tác (Inline Keyboard: ĐĂNG / HỦY)./force_post [job_id]job_idBỏ qua thời gian lập lịch, đẩy trực tiếp Job vào hàng đợi ưu tiên của Module Đăng bài (Playwright)."⚡ Đang tiến hành đăng ngay lập tức video ID: #X lên hệ thống..."IV. QUY TRÌNH BIẾN ĐỔI PIPELINE TUẦN TỰ (8 CẤU PHẦN CORE)AI Agent khi khởi tạo Worker Python cần bám sát cấu trúc luồng xử lý dữ liệu khép kín sau:1.Phân tích & Lập kế hoạch 30 ngày (Bước 1 & 7):Trạng thái: PENDING.Worker nhận thông tin Campaign. Gọi LLM Agent (Model: Gemini 1.5 Flash hoặc GPT-4o-mini) với cấu trúc prompt lập lịch. Đầu ra phải là một mảng dữ liệu phân bổ đồng đều chủ đề 30 ngày, không trùng lặp, định hình rõ hướng đi nội dung để lưu vào DB.2.Xây dựng Nội dung Chi tiết & Câu Hook (Bước 2 & 3):Trạng thái: AI_PROCESSING.LLM Agent lấy ý tưởng của ngày hiện tại, triển khai kịch bản văn bản hoàn chỉnh 60 giây. Áp dụng quy chuẩn viết: Câu ngắn, ngắt nghỉ tự nhiên, cấu trúc 3 giây đầu tiên chứa các câu mở đầu kích thích cao (Hook).3.Tách Phân cảnh & Trích xuất Từ khóa Visual (Bước 4 & 6):Trạng thái: AI_PARSED.Hệ thống phân tích kịch bản tổng, bóc tách thành các đoạn phân cảnh (mỗi cảnh từ 3 đến 5 giây). LLM thực hiện nhiệm vụ dịch nghĩa ngữ cảnh sang các từ khóa tìm kiếm hình ảnh bằng tiếng Anh (Visual English Search Keywords) để tối ưu khâu quét asset.4.Tổng hợp Giọng đọc & Trích xuất Timestamp (Bước 5):Trạng thái: AUDIO_COMPOSED.Chuyển văn bản kịch bản sang giọng nói qua công cụ edge-tts (Sử dụng các giọng đọc tự nhiên như vi-VN-HoaiAnNeural hoặc vi-VN-NamMinhNeural). Trong quá trình stream âm thanh, cấu hình bắt buộc hàm WordBoundary để lấy chính xác thời gian bắt đầu và kết thúc của từng từ đơn.5.Quét & Tải Tài nguyên Tự động (Asset Ingestion):Trạng thái: ASSETS_READY.Hệ thống gọi đồng thời (Asynchronous requests) các API của Pexels/Pixabay dựa trên Visual English Search Keywords thu được ở Bước 4. Tải về các tệp video dạng dọc (9:16), độ phân giải Full HD về thư mục lưu trữ tạm thời (/tmp/assets/).6.Hòa trộn Biên tập Video (Media Core Engine):Trạng thái: RENDERED.Kích hoạt tiến trình biên tập đồ họa bằng MoviePy. Thực hiện: Cắt các video nền tương thích với độ dài của từng phân cảnh, ghép đè luồng âm thanh gốc, chèn nhạc nền nhẹ dạng lofi (Âm lượng hạ thấp xuống -22dB).7.Vẽ Phụ đề Động & Tối ưu SEO (Bước 5 & 8):Trạng thái: RENDERED_SUBTITLED.Đọc dữ liệu timestamps từ Bước 5, tính toán phân chia cụm chữ phụ đề (Không quá 4 từ/dòng). Tạo các đối tượng TextClip có đổ bóng, viền đen nổi bật. Đè luồng chữ này lên trung tâm video. Đồng thời gọi LLM sinh tiêu đề và chuỗi hashtag tối ưu thuật toán tìm kiếm.8.Kích hoạt Stealth Publisher Đăng bài:Trạng thái: PUBLISHED.Khi đến khung giờ cấu hình hoặc nhận lệnh duyệt từ Telegram, hệ thống chuyển giao đường dẫn file .mp4 hoàn chỉnh cùng bộ siêu dữ liệu SEO sang module Playwright Stealth để thực hiện đăng tải an toàn lên nền tảng TikTok Studio.V. ĐỒNG BỘ THỜI GIAN VIDEO & PHỤ ĐỀ (SYNCHRONIZATION ALGORITHM)Để tạo hiệu ứng chữ nhảy (Karaoke Style) thu hút giữ chân người xem mà không làm tăng chi phí token phần mềm, AI Agent triển khai thuật toán tính toán ma trận thời gian theo cấu trúc sau:1. Định dạng mảng Timestamp đầu vào (Sinh từ Edge-TTS WordBoundary)JSON[
  {"word": "Dừng", "start_ms": 100, "end_ms": 400},
  {"word": "lại", "start_ms": 450, "end_ms": 700},
  {"word": "ba", "start_ms": 750, "end_ms": 950},
  {"word": "giây", "start_ms": 1000, "end_ms": 1400}
]
2. Thuật toán gộp cụm từ hiển thị (Chunking Logic)AI Agent cần viết hàm gom nhóm các từ đơn thành một dòng hiển thị trên màn hình dựa theo quy tắc:Tổng số lượng từ trong một cụm không vượt quá 4 từ.Thời gian hiển thị của một cụm chữ = end_ms của từ cuối cùng trừ đi start_ms của từ đầu tiên trong cụm.3. Cấu hình định dạng Text hiển thị trên Video (MoviePy Code Specification)Font chữ: Chọn các font nét dày, không lỗi tiếng Việt (Ví dụ: Montserrat-ExtraBold, Impact).Kích thước: fontsize=65.Hiệu ứng màu sắc: Chữ mặc định màu Trắng (color='white'), bổ sung Viền đen (stroke_color='black', stroke_width=3) để chữ hiển thị rõ ràng trên mọi gam màu của video nền.Vị trí: Căn giữa trục X, trục Y đặt ở vị trí phân bổ 2/3 màn hình từ trên xuống (pos=('center', 1280) trên khung hình 1080x1920).VI. BẢO MẬT & GIẢ LẬP TRÌNH DUYỆT (ANTI-BAN & STEALTH PROTOCOL)Hệ thống bắt buộc phải vượt qua các chốt chặn phát hiện tự động hóa của hệ thống bảo mật TikTok Studio. Khi khởi tạo instance trình duyệt bằng Playwright, AI Agent phải nạp các cấu hình kỹ thuật sau:Python# Chỉ thị triển khai cấu hình Playwright chống gậy quét bot
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

def create_stealth_browser_instance(user_data_directory):
    playwright = sync_playwright().start()
    
    # Sử dụng kênh trình duyệt Chrome thực tế được cài đặt trên OS
    browser_context = playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_directory,
        headless=True,
        channel="chrome",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            "--no-sandbox"
        ]
    )
    
    page = browser_context.pages[0]
    # Áp dụng script ghi đè các thuộc tính nhận diện robot của Cloudflare
    stealth_sync(page)
    
    return browser_context, page
Chiến thuật tương tác mô phỏng hành vi người dùng (Human-like behavior):Nhập dữ liệu Text: Tuyệt đối không dùng hàm .fill() lập tức điền toàn bộ chuỗi ký tự vào ô Caption. Phải dùng hàm duyệt qua từng ký tự và thiết lập độ trễ ngẫu nhiên từ 50ms đến 150ms giữa mỗi lần nhấn phím:$$\Delta t_{\text{key}} = \text{random}(50, 150)\text{ ms}$$Tương tác chuột: Các thao tác di chuyển đến nút "Upload" hoặc nút "Đăng" phải cấu hình thời gian chờ ngẫu nhiên sau khi trang web hoàn tất việc tải tài nguyên.VII. MA TRẬN XỬ LÝ SỰ CỐ & TỰ PHỤC HỒI (SELF-HEALING MATRIX)Để AI Agent tự theo dõi sát sao và vận hành dự án liên tục mà không cần can thiệp thủ công, hệ thống cần cấu hình bộ bắt lỗi ngoại lệ (Exception Handling) theo bảng ma trận sau:Điểm nghẽn lỗi (Fail Point)Nguyên nhân xác địnhChiến lược tự phục hồi của Hệ thống (Auto-Recovery)Hành động thông báo qua ChatbotLLM_GEN_ERRORLỗi kết nối mạng đến máy chủ AI hoặc vượt hạn mức gói (Rate Limit).Tự động chuyển đổi Model (Fallback): Nếu dùng Gemini lỗi, tự chuyển sang GPT-4o-mini. Thực hiện thử lại sau 30 giây.Ghi log hệ thống dạng WARN vào bảng process_realtime_logs.ASSET_404_ERRORAPI kho ảnh không tìm thấy video dọc tương ứng với từ khóa chuyên sâu.Rút gọn từ khóa về dạng danh từ cơ bản (Ví dụ: "crypto trading chart analysis" rút thành "finance"). Nếu vẫn lỗi, lấy video nền trừu tượng mặc định (Abstract background).Ghi nhận thông tin thay thế vào tiến trình log.RENDER_RAM_SPIKEMoviePy gặp lỗi tràn bộ nhớ (Memory Leak) do xử lý luồng video gốc nặng hơn dung lượng RAM hệ thống.Kích hoạt lệnh giải phóng bộ nhớ đệm (Python Garbage Collector), tiến hành hạ độ phân giải đầu vào của asset xuống 720p trước khi đưa vào hàm phối trộn đồ họa.Đổi trạng thái Job sang RETRY. Nếu lỗi tiếp diễn quá 3 lần chuyển thành FAILED.COOKIE_EXPIREDSession đăng nhập TikTok lưu trong file cookies.json hết hiệu lực, xuất hiện màn hình yêu cầu mã OTP/Captcha.Dừng tiến trình đăng bài ngay lập tức. Chụp lại ảnh màn hình trình duyệt lỗi tại thời điểm đó (page.screenshot(path='error.png')).Bắn thông báo khẩn cấp (Alert) trực tiếp vào ô chat của chủ kênh kèm theo file ảnh chụp màn hình để yêu cầu nạp lại cookie mới.🎯 Hướng dẫn cho AI Agent thực thi: Hãy đọc kỹ toàn bộ sơ đồ cấu trúc dữ liệu MySQL, sơ đồ dịch chuyển trạng thái (State Machine) và các tham số thuật toán đồng bộ thời gian trong tài liệu này để bắt đầu khởi tạo cấu trúc mã nguồn cho dự án một cách đồng bộ nhất.