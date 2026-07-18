import asyncio
import os
import sys

# Thêm thư mục root vào path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


from worker.infrastructure.douyin_client import download_video_link

async def test_douyin_download():
    # Sử dụng link Douyin Note (slideshow) thực tế hoặc giả định để kiểm tra luồng phân nhánh
    note_url = "https://www.douyin.com/note/7361815152865955113"
    
    print(f"[TEST] Bắt đầu tải link Douyin Note: {note_url}")
    output_dir = "worker/temp_assets"
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        path, title = await download_video_link(job_id=999, url=note_url, output_dir=output_dir)
        print("[TEST] Tải thành công!")
        print(f"Đường dẫn file: {path}")
        print(f"Tiêu đề gốc: {title}")
    except Exception as e:
        print(f"[TEST] Thất bại với lỗi: {e}")

if __name__ == "__main__":
    asyncio.run(test_douyin_download())
