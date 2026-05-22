ĐẶC TẢ KỸ THUẬT V2.0: HỆ THỐNG BIÊN TẬP VIDEO CHILL-OUT AUDIO-REACTIVE TỰ ĐỘNGI. TƯ DUY KIẾN TRÚC MỚI (2026 CORE PARADIGM SHIFT)Trong các hệ thống tự động hóa video thế hệ cũ, việc dựng hình và chèn chữ phụ thuộc hoàn toàn vào các thư viện CPU-bound như MoviePy, dẫn đến 2 điểm yếu lớn: Tràn bộ nhớ RAM (Memory Leak) và hiệu ứng đồ họa bị thô cứng.Kiến trúc V2.0 chuyển dịch sang mô hình Playwright Canvas-to-FFmpeg Pipeline:Audio-Reactive Data Extraction: Dùng Python phân tích file âm thanh bằng thuật toán Biến đổi Fourier nhanh (Fast Fourier Transform - FFT) để trích xuất biên độ nhảy của âm bass, mid, treble theo từng mili-giây.WebGL/Canvas Rendering: Đẩy dữ liệu kịch bản, phụ đề và biên độ sóng nhạc vào một trang HTML5/WebGL cục bộ. Dùng trình duyệt ẩn danh (Playwright Headless) để render trang web này ở tốc độ 60FPS ổn định tuyệt đối.Stream Piping: Chụp luồng hình ảnh trực tiếp từ Canvas trình duyệt và đẩy thẳng (Pipe) vào FFmpeg để nén thành file .mp4 trong thời gian thực. Phương pháp này giúp render video đẹp như phần mềm chuyên nghiệp (After Effects) nhưng tốn ít hơn 70% tài nguyên CPU/RAM.II. THUẬT TOÁN ĐỒNG BỘ SÓNG NHẠC (AUDIO-REACTIVE FFT ALGORITHM)Để sóng nhạc và các thành phần đồ họa (khung đĩa than xoay, tiến trình bar) co giãn nhịp nhàng theo giai điệu bài hát (đặc biệt là các bản nhạc trẻ, nhạc Remix hot trend), Worker Python sẽ chạy một script phân tích tần số âm thanh trước khi render.1. Phân tách biên độ âm thanh bằng thư viện librosa và scipyHệ thống sẽ bóc tách tần số âm thanh từ file .mp3 thành một chuỗi mảng JSON chứa cường độ của dải Bass (tần số thấp từ 20Hz đến 250Hz), đại diện cho nhịp đập chính của bài hát:Pythonimport numpy as np
import librosa
import json

def extract_audio_reactive_data(audio_path, fps=30): # Tải file nhạc với tần số lấy mẫu chuẩn 22050Hz
y, sr = librosa.load(audio_path, sr=22050)

    # Tính toán độ dài khung hình dựa trên FPS của video
    hop_length = int(sr / fps)

    # Thực hiện biến đổi Fourier ngắn hạn (STFT)
    stft = np.abs(librosa.stft(y, hop_length=hop_length))

    # Trích xuất dải tần số Bass (Dòng 0 đến 10 trong ma trận STFT)
    bass_frequencies = stft[0:10, :]
    bass_energy = np.mean(bass_frequencies, axis=0)

    # Chuẩn hóa dữ liệu về khoảng từ 0.0 đến 1.0 để tiện tính toán đồ họa
    if np.max(bass_energy) > 0:
        bass_energy = bass_energy / np.max(bass_energy)

    # Xuất ra mảng JSON chứa biên độ theo từng khung hình (Frame)
    return bass_energy.tolist()

2.  Áp dụng dữ liệu vào Visual ObjectGiao diện Trình phát nhạc nghệ thuật sẽ nhận mảng JSON này. Tại khung hình thứ $t$, nếu giá trị Bass Energy cao ($>0.8$), các hiệu ứng sau sẽ tự động kích hoạt trên Canvas:Hiệu ứng Nhịp đập (Pulse Effect): Khung đĩa nhạc hoặc khung Lyrics tự động phóng to ra $15\%$ (Scale nhân với $1.15$).Hiệu ứng Phát sáng (Neon Glow Effect): Tăng cường độ đổ bóng đổ sáng (Shadow Blur) của chữ theo nhịp nhạc.III. QUY TRÌNH THỰC THI PIPELINE V2.0 CỦA AGENTĐể triển khai, AI Agent phải tuân thủ nghiêm ngặt chuỗi quy trình tự động hóa tích hợp 2026 dưới đây:1.Săn Nhạc Hot Trend & Nhận Lệnh Qua Telegram:Trạng thái: BOT_RECEIVE.Người dùng ra lệnh qua Telegram Bot. Hệ thống kích hoạt module Scraper chạy Playwright ngầm quét trang TikTok Creative Center để bốc tách Top 1 bài hát đang đứng đầu bảng xếp hạng Việt Nam, lấy tên bài hát, ca sĩ và tải file âm thanh mẫu.2.Phân Tích Ngữ Cảnh & Khớp Tệp Màu Điện Ảnh (Cinematic):Trạng thái: AI_CREATIVE.LLM (Gemini 1.5 Flash) đọc tên bài hát và lời dịch (Lyrics) để phân tích "Mood" (Tâm trạng). Kết quả trả về một nhãn cảm xúc: SAD_RAIN, CYBERPUNK_NIGHT, hoặc COZY_CHILL. Dựa vào nhãn này, hệ thống tự động bốc bộ lọc màu (Color LUT) tương ứng.3.Tìm Kiếm Kho Video Nền Theo Trạng Thái Cảm Xúc:Trạng thái: ASSET_ClUSTERING.Hệ thống gọi API Pexels tải 3 đoạn video dọc (9:16) siêu nghệ thuật theo từ khóa cảm xúc của Bước 2. Áp dụng bộ lọc video ngắn, tiến hành xử lý làm mờ (Blur 10px) và giảm độ sáng (Brightness 60%) để làm nền bổ trợ cho phần chữ nổi phía trước.4.Chạy Thuật Toán FFT Trích Xuất Biên Độ Giai Điệu:Trạng thái: SIGNAL_PROCESSING.Worker Python chạy script xử lý tín hiệu số âm thanh qua librosa. Bóc tách toàn bộ file âm thanh thành mảng dữ liệu biến thiên cường độ nhạc (Audio Dynamics Array) tương thích với mốc thời gian hiển thị video.5.Khởi Tạo Giao Diện Web Trực Quan Để Chuẩn Bị Render:Trạng thái: WEB_DOM_BUILD.Node.js Backend tạo ra một file render_template.html tạm thời. File này chứa mã nguồn HTML5/JS kết hợp CSS Animation để dựng sẵn khung đĩa nhạc xoay, thanh tiến trình chạy, chữ lyrics chạy và các thanh sóng nhạc (Audio Spectrum bars).6.Chụp Luồng Trình Duyệt Bằng Playwright & Đẩy Vào FFmpeg:Trạng thái: STREAM_RENDERING.Mở Playwright ở chế độ ẩn danh, load file HTML vừa tạo. Chạy một vòng lặp JS nạp dữ liệu Bass Energy của Bước 4 để sóng nhạc nhảy động. Playwright liên tục chụp lại frame hình (Screenshots) dưới dạng mảng byte hiệu năng cao và đẩy trực tiếp vào luồng ghi của FFmpeg.7.Đóng Gói Siêu Dữ Liệu Tăng Trưởng (Anti-Flop SEO):Trạng thái: METADATA_SEO.LLM viết đoạn văn bản mô tả (Caption) lôi cuốn, chèn tự động các icon âm nhạc hợp lý và bộ 5 Hashtags đang có lượng truy cập lớn nhất tại Việt Nam liên quan đến bài hát đó (Ví dụ: #nhachaymoingay, #lofi, #music).8.Kích Hoạt Trình Duyệt Ẩn Đăng Bài Lên TikTok Studio:Trạng thái: PUBLISHED.Hệ thống kiểm tra hàng đợi đặt lịch (Scheduler), đến đúng khung giờ vàng (Ví dụ: 22:00 đêm), module Playwright Stealth tự động khởi chạy, nạp tệp session tiktok_user_state.json và thực hiện chuỗi thao tác đăng bài tự động như người thật.IV. ĐẶC TẢ GIAO DIỆN WEB RENDER CHUYÊN SÂU (MÃ WEBGL/CSS CỐT LÕI)Để Agent biết cách xây dựng trang giao diện nghe nhạc trên trình duyệt, đây là đoạn mã HTML/JS cốt lõi tạo ra hiệu ứng Cột sóng nhạc nhảy động kết hợp hiệu ứng đĩa nhạc xoay dựa trên dữ liệu FFT nạp từ backend:HTML<!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <style>
            body {
                margin: 0; width: 1080px; height: 1920px;
                background-color: #050505; font-family: 'Montserrat', sans-serif;
                overflow: hidden; position: relative;
            }
            #bg-video-placeholder {
                position: absolute; width: 100%; height: 100%; object-fit: cover; z-index: 1;
            }
            .music-player-card {
                position: absolute; bottom: 200px; left: 64px; right: 64px;
                height: 450px; background: rgba(0, 0, 0, 0.6);
                border-radius: 30px; backdrop-filter: blur(20px);
                z-index: 10; padding: 40px; box-sizing: border-box;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            .spectrum-container {
                display: flex; justify-content: center; align-items: flex-end;
                gap: 6px; height: 100px; margin-top: 30px;
            }
            .bar {
                width: 8px; height: 10px; background: linear-gradient(to top, #ffffff, #888888);
                border-radius: 4px; transition: height 0.05s ease;
            }
        </style>
    </head>
    <body>
        <!-- Video nền chill-out -->
        <video id="bg-video-placeholder" src="temp_stock_video.mp4" autoplay loop muted></video>

        <!-- Khung Trình Phát Nhạc Nghệ Thuật -->
        <div class="music-player-card">
            <h2 style="color: white; margin: 0; font-size: 42px;" id="song-title">Tên Bài Hát Hot Trend</h2>
            <p style="color: #aaaaaa; margin: 10px 0; font-size: 28px;" id="artist-name">Tên Ca Sĩ</p>

            <!-- Khung hiển thị sóng nhạc động -->
            <div class="spectrum-container" id="spectrum">
                <!-- Sinh tự động 20 cột sóng nhạc bằng JS -->
            </div>
        </div>

        <script>
            // Hệ thống backend sẽ tự động chèn mảng dữ liệu FFT vào đây lúc khởi tạo file
            const fftData = [/* Mảng số thực biên độ âm thanh sinh từ Python */];
            const spectrumContainer = document.getElementById('spectrum');
            const totalBars = 24;

            // Tạo các cột sóng nhạc hình vòm
            for(let i=0; i<totalBars; i++) {
                let bar = document.createElement('div');
                bar.className = 'bar';
                spectrumContainer.appendChild(bar);
            }

            const bars = document.querySelectorAll('.bar');

            // Hàm cập nhật trạng thái đồ họa động theo thời gian thực (tính bằng Frame)
            function updateVisualsForFrame(frameIndex) {
                const currentBass = fftData[frameIndex] || 0.1;

                // Cập nhật độ cao các cột sóng nhạc nhảy theo biên độ Bass kèm tính toán ngẫu nhiên nhẹ cho mượt
                bars.forEach((bar, index) => {
                    const waveFactor = Math.sin((index / totalBars) * Math.PI); // Tạo hiệu ứng hình vòm cầu
                    const calculatedHeight = 10 + (currentBass * 90 * waveFactor) + (Math.random() * 10);
                    bar.style.height = `${calculatedHeight}px`;
                });

                // Hiệu ứng nhịp đập (Pulse effect) phóng to toàn bộ Card khi nhạc đập mạnh
                const card = document.querySelector('.music-player-card');
                const scale = 1 + (currentBass * 0.04);
                card.style.transform = `scale(${scale})`;
            }

            // Expose hàm này ra cửa sổ global để Playwright từ bên ngoài có thể gọi điều khiển từng frame lúc chụp ảnh
            window.updateVisualsForFrame = updateVisualsForFrame;
        </script>

    </body>
    </html>
    V. CƠ CHẾ KIỂM TRA CHẤT LƯỢNG KHÉP KÍN (QUALITY GATE)Trước khi chuyển giao video sang module Đăng bài, Agent cần thực hiện 2 bộ lọc kiểm tra tự động (Automated Sanitization Checks) để loại bỏ 100% video lỗi:Check Video File Size & Duration: Sử dụng thư viện ffprobe để quét file video đầu ra. Nếu dung lượng file dưới 2MB (dấu hiệu render thiếu asset) hoặc thời lượng âm thanh và hình ảnh lệch nhau quá 0.5 giây, hệ thống lập tức huỷ Job, đổi trạng thái sang FAILED và gửi tin nhắn báo lỗi về Telegram của bạn.Check Frame Blackout: Quét ngẫu nhiên 3 frame hình (ở giây thứ 1, giữa video, và giây cuối). Nếu có frame nào trả về màu đen thuần túy (#000000 - lỗi mất nguồn video gốc của Pexels), hệ thống sẽ kích hoạt hàm tự sửa lỗi (Self-healing), bốc video nền dự phòng và tiến hành render lại từ đầu.Tài liệu này chứa đựng toàn bộ tư duy kiến trúc và thuật toán xử lý media tiên tiến nhất hiện nay. Hãy dán trực tiếp tệp đặc tả này vào ngữ cảnh làm việc của AI Agent để nó tự động lên kế hoạch phân chia cấu trúc thư mục và lập trình hoàn chỉnh dự án AgentTiktok của bạn!
