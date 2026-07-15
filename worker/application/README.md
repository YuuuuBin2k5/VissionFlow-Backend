# Worker Application Layer

`worker/application/` chứa các lát cắt điều phối use case của pipeline. Layer này được phép gọi `domain`, `infrastructure` và `services` để thực hiện một luồng nghiệp vụ cụ thể.

Quy tắc:

- Orchestrate, không nhét thêm helper thuần nếu helper đó thuộc domain.
- Không chứa low-level browser/DB implementation chi tiết nếu có thể đưa sang infrastructure.
- Không được import ngược từ `main.py`.

Các module hiện có:

- `planning_use_case.py`: luồng PLANNING, đọc campaign, gọi LLM lập kế hoạch và sinh lịch job an toàn.
- `render_use_case.py`: luồng RENDER, gồm dub render, classic render, split-screen render và music reactive render.
- `publish_use_case.py`: luồng publish TikTok từ video đã render.
