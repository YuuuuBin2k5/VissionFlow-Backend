"""
Render Strategy Registry
=========================
Danh sách tất cả render strategies được đăng ký, theo thứ tự ưu tiên.

Quy tắc thứ tự:
- Specific strategies đặt trước (is_music_reactive, is_translate_dub)
- StandardRenderStrategy PHẢI đặt cuối cùng (fallback, can_handle luôn True)

Để thêm render mode mới (vd: AI Avatar, 3D Cinematic):
  1. Tạo file: worker/application/render_strategies/avatar_strategy.py
  2. Kế thừa RenderStrategy và implement can_handle() + execute()
  3. Thêm vào get_render_strategies() dưới đây TRƯỚC StandardRenderStrategy
  → File render_use_case.py KHÔNG cần sửa (OCP compliant)
"""
from __future__ import annotations

from worker.application.render_strategies.base import RenderStrategy


def get_render_strategies() -> list[RenderStrategy]:
    """
    Factory function trả về danh sách đầy đủ các render strategies.
    Được gọi mỗi khi handle_render() được chạy trong worker runtime.
    Lazy import để tránh ImportError trong môi trường không có moviepy/playwright.
    """
    from worker.application.render_strategies.music_reactive_strategy import MusicReactiveStrategy
    from worker.application.render_strategies.dubbing_strategy import DubbingStrategy
    from worker.application.render_strategies.standard_strategy import StandardRenderStrategy

    return [
        MusicReactiveStrategy(),   # is_music_reactive → True
        DubbingStrategy(),         # is_translate_dub  → True
        StandardRenderStrategy(),  # Fallback — LUÔN đặt cuối cùng
    ]


# Alias for backward compatibility
RENDER_STRATEGIES = get_render_strategies
