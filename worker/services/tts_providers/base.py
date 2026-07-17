"""
TTS Provider Base — Strategy Pattern
=====================================
Mọi TTS provider phải kế thừa từ TTSProvider và implement phương thức synthesize().
Điều này đảm bảo Open/Closed Principle: thêm provider mới = thêm file mới, không sửa TTSEngine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class WordTimestamp:
    """Biểu diễn thời điểm xuất hiện của một từ trong audio."""
    word: str
    start_ms: int
    end_ms: int

    def to_dict(self) -> dict:
        return {"word": self.word, "start_ms": self.start_ms, "end_ms": self.end_ms}


class TTSProvider(ABC):
    """
    Strategy interface cho tất cả TTS providers.

    Mỗi implementation phải trả về danh sách WordTimestamp —
    thể hiện chính xác thời điểm từng từ được phát ra trong audio.
    """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice_profile: dict,
    ) -> list[dict]:
        """
        Sinh file audio từ text và trả về word-level timestamps.

        Args:
            text:          Văn bản đã được chuẩn hóa nhịp điệu.
            output_path:   Đường dẫn tuyệt đối để lưu file audio (.mp3).
            voice_profile: Dict cấu hình giọng từ VOICE_REGISTRY
                           (vd: {"source": "edge-tts", "voice": "vi-VN-NamMinhNeural", "rate": "-6%"}).

        Returns:
            list[dict]: Danh sách {"word": str, "start_ms": int, "end_ms": int}.
                        Trả về list rỗng [] nếu không lấy được timestamps chính xác.

        Raises:
            Exception: Khi không thể sinh audio sau tất cả các lần retry.
        """
        ...
