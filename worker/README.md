# Worker Architecture Guide

## Mục đích

`worker/` là runtime Python xử lý render/media pipeline và publisher path cho AgentBot. Worker nhận job từ backend/orchestrator, đọc dữ liệu job, render video, cập nhật tiến độ và đăng/publish khi được yêu cầu.

Worker dùng mô hình **Modular Monolith + Pipeline Use Cases + Ports/Adapters nhẹ**. Không tách microservice trong giai đoạn này.

## Bản đồ module

```text
worker/
├── main.py              # CLI entrypoint: parse args and route PLANNING/RENDER/PUBLISH
├── domain/              # Pure rules: scheduling, metadata parsing, caption policy
├── application/         # Use-case orchestration slices
├── infrastructure/      # DB, browser/download, external integration adapters
├── services/            # Media, music, render, publisher concrete services
├── utils/               # Low-level helpers
└── config.py            # Env-based configuration
```

## Quy tắc viết code

- `main.py` chỉ điều phối command, không thêm business rule mới.
- Logic thuần, dễ test đặt trong `domain/`.
- Luồng render/publish/planning đặt trong `application/`.
- Code có side effect như DB, browser, filesystem, download đặt trong `infrastructure/`.
- Các implementation nặng đã có như media, music, publisher giữ trong `services/`.
- Telemetry lên cockpit phải đi qua `services/cockpit_bridge.py` hoặc adapter được chỉ định.

## Mẫu import chuẩn

```python
from worker.domain.scheduling import build_safe_campaign_schedule
from worker.infrastructure.database import get_db_connection, log_realtime_progress
from worker.application.publish_use_case import handle_publish
```

## Điều cấm kỵ

- Không tạo thêm `utils.py` tổng hợp cho mọi thứ.
- Không để domain import DB, HTTP, browser hoặc service nặng.
- Không để service import ngược application use case.
- Không hard-code secret/API key/path production.
- Không đổi behavior render/publish trong một lượt refactor chỉ nhằm tách file.
