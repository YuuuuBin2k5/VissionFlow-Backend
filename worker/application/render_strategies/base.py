"""
Render Strategy Base — Strategy Pattern
=========================================
Abstract interface cho tất cả các render mode.
Thêm render mode mới = thêm 1 class mới, không sửa render_use_case.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from worker.domain.render_contract import RenderContract


class RenderStrategy(ABC):
    """
    Strategy interface cho các chế độ render video khác nhau.

    Quy tắc implement:
    - can_handle() phải là deterministic — không có side effect
    - execute() phải trả về đường dẫn video đầu ra (str)
    - Mọi cập nhật trạng thái DB trong execute() dùng VideoJobRepository
    - Log dùng log_realtime_progress() từ infrastructure.database
    """

    @abstractmethod
    def can_handle(self, contract: RenderContract) -> bool:
        """
        Kiểm tra xem strategy này có xử lý được contract không.
        Gọi trước execute() — không bao giờ có side effect.
        """
        ...

    @abstractmethod
    async def execute(self, job: dict, contract: RenderContract) -> str:
        """
        Thực thi pipeline render và trả về đường dẫn file video đầu ra.

        Args:
            job:      Dict đầy đủ của video_pipeline_job từ DB.
            contract: RenderContract chứa metadata render đã được parsed.

        Returns:
            Đường dẫn tuyệt đối của file video đã render (.mp4).

        Raises:
            Exception: Bất kỳ lỗi nào trong quá trình render.
                       render_use_case sẽ catch và ghi vào DB.
        """
        ...
