# 🤖 CHAT-DRIVEN TIKTOK AUTOMATION TOOL

Hệ thống tự động hóa lập kế hoạch, tạo nội dung, tổng hợp giọng nói tiếng Việt, render video dọc chất lượng cao có phụ đề Karaoke, và tự động đăng bài lên TikTok Studio hoàn toàn thông qua giao diện Chat Telegram.

---

## 📸 Kiến Trúc Hệ Thống (System Topology)
Hệ thống được thiết kế theo kiến trúc hướng sự kiện, gồm 3 tầng chính tách biệt để tránh nghẽn luồng xử lý đồ họa nặng:
1. **Tầng 1 (Orchestrator Engine)**: Node.js / Express / TypeScript / Prisma quản lý cơ sở dữ liệu MySQL, tiếp nhận lệnh từ Telegram Bot, và điều phối tác vụ vào hàng đợi **BullMQ (Redis)**.
2. **Tầng 2 (Core Media Worker)**: Python 3.10+ tích hợp **Gemini 1.5 Flash**, **Edge-TTS**, **Pexels API** và **MoviePy + Pillow** để biên soạn kịch bản, tải video nền dọc, tạo giọng đọc và ghép phụ đề Karaoke nhảy chữ thông minh.
3. **Tầng 3 (Stealth Publishing Agent)**: **Playwright Stealth Engine** tự động hóa đăng bài giả lập hành vi con người an toàn tuyệt đối lên TikTok Studio.

---

## 🛠️ Hướng Dẫn Cài Đặt (Installation Guide)

### 1. Yêu Cầu Cấu Hình Hệ Thống
* Hệ điều hành: **Windows 10/11**
* **Node.js** v18+ hoặc v20+
* **Python** v3.10+ (Đã thêm vào biến môi trường PATH)
* **Docker Desktop** (Để chạy nhanh MySQL & Redis)
* Trình duyệt **Google Chrome** thực tế đã cài đặt trên máy.

---

### 2. Thiết Lập Cơ Sở Dữ Liệu & Hàng Đợi (Docker Compose)
Ở thư mục gốc dự án, mở Terminal và chạy lệnh sau để khởi động MySQL 8.0 và Redis 7.0:
```bash
docker-compose up -d
```
*Lưu ý: Đảm bảo cổng `3306` (MySQL) và `6379` (Redis) không bị chiếm dụng trước khi khởi chạy.*

---

### 3. Cấu Hình Tầng 1: Orchestrator (Node.js & Telegram)
1. Di chuyển vào thư mục `orchestrator`:
   ```bash
   cd orchestrator
   ```
2. Cài đặt các thư viện Node.js cần thiết:
   ```bash
   npm install
   ```
3. Cấu hình file `.env`:
   Mở file `orchestrator/.env` và cập nhật thông tin:
   * `TELEGRAM_BOT_TOKEN`: Dán token nhận được từ **@BotFather** trên Telegram.
   * `DATABASE_URL`: Giữ nguyên nếu chạy qua Docker.
4. Chạy Prisma Migrations để tự động khởi tạo cấu trúc bảng dữ liệu trong MySQL:
   ```bash
   npx prisma migrate dev --name init
   ```
5. Khởi động Orchestrator ở chế độ phát triển:
   ```bash
   npm run dev
   ```

---

### 4. Cấu Hình Tầng 2 & 3: Core Python Worker
1. Di chuyển vào thư mục `worker`:
   ```bash
   cd ../worker
   ```
2. Tạo môi trường ảo (Khuyên dùng trên Windows để tránh xung đột thư viện):
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Cài đặt các thư viện Python từ `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```
4. Thiết lập các biến môi trường cấu hình:
   * **Pexels API Key**: Cấu hình trong `worker/.env` bằng biến `PEXELS_API_KEY`.
   * **Gemini API Key**: Đặt biến môi trường hệ thống hoặc truyền vào qua Terminal:
     * Trên CMD Windows: `set GEMINI_API_KEY=khóa_của_bạn`
     * Trên PowerShell Windows: `$env:GEMINI_API_KEY="khóa_của_bạn"`
5. **Cực kỳ quan trọng**: Cài đặt các driver trình duyệt Playwright và cài đặt Chrome:
   ```bash
   playwright install chrome
   ```

---

## 🚀 Hướng Dẫn Vận Hành & Sử Dụng (Operation & Usage)

### 1. Khởi động Hệ Thống
1. Chạy Docker Compose (MySQL, Redis).
2. Chạy Orchestrator: `npm run dev` tại thư mục `orchestrator`.
   *Bạn sẽ thấy log thông báo Telegram Bot đã online.*
3. Kích hoạt môi trường ảo Python và giữ màn hình sẵn sàng nhận Job.

### 2. Tương tác với Telegram Bot
Mở ô chat với Bot trên Telegram và sử dụng các lệnh điều khiển:

* **Khởi chạy Chiến dịch**:
  👉 `/start_campaign [Chủ đề] | [Đối tượng]`
  *Ví dụ:* `/start_campaign Lập trình Python cho người mới | Học sinh sinh viên công nghệ`
  *Hệ thống sẽ ghi nhận chiến dịch, đẩy tác vụ lập lịch vào hàng đợi, gọi Gemini lên ý tưởng 30 video và tạo 30 Jobs tương ứng.*

* **Kiểm tra tiến độ kênh**:
  👉 `/status`
  *Xem báo cáo thống kê trực quan số lượng video đang chờ xử lý, đã render, đã duyệt hay đã đăng.*

* **Xem trước & Phê duyệt video**:
  👉 `/preview [job_id]`
  *(Ví dụ: `/preview 1`)*
  *Bot sẽ gửi trực tiếp file video `.mp4` hoàn chỉnh đã chèn phụ đề Karaoke chuyên nghiệp kèm Inline Keyboard gồm 2 nút bấm:*
  * `🚀 DUYỆT ĐĂNG NGAY`: Cập nhật trạng thái và tự động gọi Playwright đăng bài.
  * `❌ HỦY JOB`: Hủy bỏ video không phù hợp.

* **Buộc đăng tải ngay**:
  👉 `/force_post [job_id]`
  *Bỏ qua thời gian lập lịch, đẩy trực tiếp video lên TikTok Studio.*

---

## 🛡️ Cơ Chế Vượt Rào Cản Phát Hiện Bot (Stealth Protocol) & Đăng Nhập
* **Lần đầu tiên chạy đăng bài**: Trình duyệt Chromium của Playwright sẽ được kích hoạt ở chế độ **có giao diện (Headful mode)**.
* **Hành động của bạn**: Vui lòng thực hiện đăng nhập tài khoản TikTok Studio của bạn thủ công (hoặc quét mã QR) tại cửa sổ Chrome vừa hiện ra.
* **Thời gian chờ**: Trình duyệt sẽ đợi tối đa **90 giây** để bạn thao tác.
* Sau khi đăng nhập thành công, session của bạn sẽ được lưu trữ an toàn trong thư mục cục bộ `worker/chrome_profile`. Các lần đăng bài tiếp theo sẽ hoàn toàn tự động mà không cần bạn đăng nhập lại!
* Hệ thống mô phỏng việc gõ Caption và Hashtags với độ trễ ngẫu nhiên từ $50\text{ms}$ đến $150\text{ms}$ giữa các phím để chống việc quét spam.

---

## 🛠️ Ma Trận Tự Phục Hồi Sự Cố (Self-Healing Matrix)
* **Lỗi API Gemini**: Tự động chuyển đổi kịch bản fallback mẫu thiết lập sẵn để giữ pipeline vận hành liên tục.
* **Lỗi tải Asset video nền**: Khi Pexels không tìm thấy từ khóa chuyên sâu, hệ thống tự động đơn giản hóa từ khóa, hoặc lấy video thiên nhiên/đồ họa trừu tượng thay thế.
* **Tràn bộ nhớ đồ họa (MoviePy RAM Spike)**: Tự động dọn dẹp bộ nhớ đệm (Garbage Collector), đóng luồng ffmpeg để giải phóng RAM tối ưu.
* **Hết hạn Session / Cookie**: Trình duyệt chụp lại ảnh màn hình lỗi lưu vào `worker/output_videos/error.png` và thông báo khẩn qua Telegram kèm hình ảnh để chủ kênh cập nhật.
