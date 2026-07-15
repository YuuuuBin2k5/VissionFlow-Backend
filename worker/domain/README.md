# Worker Domain Layer

`worker/domain/` chứa logic thuần của worker: scheduling, phân loại metadata, caption policy và các rule có thể test mà không cần DB/browser/network.

Quy tắc:

- Không import `worker.infrastructure`.
- Không import service nặng như media/render/browser.
- Không đọc/ghi file hoặc database.
- Hàm nên nhận input rõ ràng và trả output rõ ràng.

Các module hiện có:

- `scheduling.py`: lịch đăng an toàn theo preset/timezone/min gap.
- `job_metadata.py`: parse metadata, detect render mode, parse voice flag.
- `caption_policy.py`: caption và hashtag policy cho publish.
- `render_contract.py`: hợp đồng đầu vào thuần cho worker render, gom mode, stage dừng, voice và metadata trước khi application layer gọi service nặng.
