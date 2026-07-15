# Worker Infrastructure Layer

`worker/infrastructure/` chứa các adapter có side effect: database, trình duyệt, download, filesystem hoặc integration biên.

Quy tắc:

- Được đọc config/env qua `worker.config`.
- Được gọi service bridge hoặc thư viện ngoài khi cần.
- Không chứa business rule thuần nếu rule đó có thể đặt trong `domain`.
- Phải graceful fallback cho adapter không ổn định như browser/network khi luồng render không bắt buộc phải crash.

Các module hiện có:

- `database.py`: MySQL connection và realtime progress logging.
- `douyin_client.py`: Douyin browser/cookie/download adapter.
