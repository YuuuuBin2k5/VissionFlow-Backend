import asyncio


def copy_locked_file_windows(src: str, dst: str) -> bool:
    """Sao chép tệp đang bị khóa bởi tiến trình khác (như Chrome Cookies) bằng CreateFileW share flags"""
    import os
    if not os.path.exists(src):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80

        handle = kernel32.CreateFileW(
            src,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None
        )

        if handle == -1 or handle == 0xFFFFFFFF:
            return False

        buffer_size = 65536
        buffer = ctypes.create_string_buffer(buffer_size)
        bytes_read = wintypes.DWORD()

        os.makedirs(os.path.dirname(dst), exist_ok=True)

        with open(dst, "wb") as f_out:
            while True:
                res = kernel32.ReadFile(handle, buffer, buffer_size, ctypes.byref(bytes_read), None)
                if not res or bytes_read.value == 0:
                    break
                f_out.write(buffer.raw[:bytes_read.value])

        kernel32.CloseHandle(handle)
        return True
    except Exception as e:
        print(f"[copy_locked_file_windows Warning] Custom copy failed: {e}")
        return False


def harvest_cookies_via_playwright_sync(url: str, profile_dir: str):
    """Mở trang Douyin bằng Playwright để trình duyệt tự giải mã và tải Cookies, sau đó lưu ra file Netscape"""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    import time
    import os

    with sync_playwright() as p:
        try:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=True,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )
        except Exception:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )

        try:
            page = browser_context.pages[0]
            Stealth().apply_stealth_sync(page)

            # Điều hướng đến trang Douyin để nạp cookies sạch
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(4)  # Đợi 4 giây để nạp cookies đầy đủ

            cookies = browser_context.cookies()
            from worker.config import BASE_DIR
            cookies_dir = os.path.join(BASE_DIR, "worker", "temp_assets")
            os.makedirs(cookies_dir, exist_ok=True)
            cookies_path = os.path.join(cookies_dir, "douyin_cookies.txt")

            with open(cookies_path, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# This is a generated file! Do not edit.\n\n")
                for c in cookies:
                    domain = c.get("domain", "")
                    flag = "TRUE" if domain.startswith(".") else "FALSE"
                    path = c.get("path", "/")
                    secure = "TRUE" if c.get("secure", False) else "FALSE"
                    expires = c.get("expires", 0)
                    if expires is None or expires <= 0 or expires == -1:
                        expires = 2147483647
                    else:
                        expires = int(expires)
                    name = c.get("name", "")
                    value = c.get("value", "")
                    f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            print(f"[Playwright Cookie Harvest] Đã lưu {len(cookies)} cookies vào {cookies_path}")
        finally:
            browser_context.close()


def extract_douyin_video_sync(url: str, profile_dir: str) -> str:
    """Trích xuất link video stream trực tiếp từ Douyin sử dụng Stealth Playwright"""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    import time
    import os

    with sync_playwright() as p:
        try:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=True,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )
        except Exception:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )

        try:
            page = browser_context.pages[0]
            Stealth().apply_stealth_sync(page)

            captured_streams = []
            def handle_response(response):
                try:
                    u = response.url
                    if "aweme/v1/web/aweme/detail" in u:
                        data = response.json()
                        aweme = data.get("aweme_detail", {})
                        video = aweme.get("video", {})
                        play_addr = video.get("play_addr", {})
                        url_list = play_addr.get("url_list", [])
                        for stream_url in url_list:
                            if stream_url and "http" in stream_url:
                                captured_streams.append(stream_url)
                    else:
                        ct = response.headers.get("content-type", "").lower()
                        if ("video/mp4" in ct or "douyinvod.com" in u or "zjcdn.com" in u) and "uuu_265.mp4" not in u and not u.startswith("blob:"):
                            captured_streams.append(u)
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception as ge:
                print(f"[Python Worker Warning] Playwright page.goto warning: {ge}")

            time.sleep(3)  # Đợi trình phát JS khởi tạo xong

            # Nếu chưa bắt được luồng qua listener, gọi trực tiếp API aweme detail của Douyin qua session Playwright
            if not captured_streams:
                import re
                vid_match = re.search(r"/video/(\d+)", url)
                if vid_match:
                    aweme_id = vid_match.group(1)
                    api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={aweme_id}"
                    try:
                        print(f"[Python Worker] Gọi trực tiếp API aweme detail Douyin cho id: {aweme_id}...")
                        api_res = page.request.get(api_url, headers={"Referer": url})
                        if api_res.ok:
                            data = api_res.json()
                            url_list = data.get("aweme_detail", {}).get("video", {}).get("play_addr", {}).get("url_list", [])
                            for stream_url in url_list:
                                if stream_url and "http" in stream_url:
                                    captured_streams.append(stream_url)
                    except Exception as api_err:
                        print(f"[Python Worker Warning] Gọi trực tiếp API aweme detail thất bại: {api_err}")

            if captured_streams:
                print(f"[Python Worker Network Interceptor] Captured direct Douyin stream: {captured_streams[0][:100]}...")
                return captured_streams[0]

            # Đợi thẻ video xuất hiện trong DOM
            try:
                page.wait_for_selector("video", state="attached", timeout=6000)
            except Exception:
                pass

            videos = page.locator("video")
            count = videos.count()

            # Bước 1: Duyệt qua tất cả các thẻ video để tìm link stream chất lượng cao từ thẻ source lồng ghép
            for i in range(count):
                video = videos.nth(i)
                sources = video.locator("source")
                for j in range(sources.count()):
                    source_src = sources.nth(j).get_attribute("src")
                    if source_src:
                        if "uuu_265.mp4" in source_src or source_src.startswith("blob:"):
                            continue
                        return source_src

            # Bước 2: Duyệt qua các thẻ video để lấy trực tiếp thuộc tính src làm fallback
            for i in range(count):
                video = videos.nth(i)
                src = video.get_attribute("src")
                if src:
                    if "uuu_265.mp4" in src or src.startswith("blob:"):
                        continue
                    return src

            if captured_streams:
                return captured_streams[-1]

            raise RuntimeError("Không tìm thấy link video stream thực tế (chỉ phát hiện các blob URL).")
        finally:
            # Cực kỳ quan trọng: Trích xuất và lưu Cookies của phiên Playwright thành định dạng Netscape
            # để yt-dlp có thể kế thừa cookies sạch vượt qua tường lửa của Douyin!
            try:
                cookies = browser_context.cookies()
                from worker.config import BASE_DIR
                cookies_dir = os.path.join(BASE_DIR, "worker", "temp_assets")
                os.makedirs(cookies_dir, exist_ok=True)
                cookies_path = os.path.join(cookies_dir, "douyin_cookies.txt")

                with open(cookies_path, "w", encoding="utf-8") as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    f.write("# This is a generated file! Do not edit.\n\n")
                    for c in cookies:
                        domain = c.get("domain", "")
                        flag = "TRUE" if domain.startswith(".") else "FALSE"
                        path = c.get("path", "/")
                        secure = "TRUE" if c.get("secure", False) else "FALSE"
                        expires = c.get("expires", 0)
                        if expires is None or expires <= 0 or expires == -1:
                            expires = 2147483647
                        else:
                            expires = int(expires)
                        name = c.get("name", "")
                        value = c.get("value", "")
                        f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
                print(f"[Python Worker] Successfully extracted {len(cookies)} clean session cookies into {cookies_path}")
            except Exception as ce:
                print(f"[Python Worker Warning] Failed to save Playwright cookies: {ce}")

            browser_context.close()

def harvest_chrome_douyin_cookies() -> bool:
    """
    Tự động quét tất cả các Profile Chrome trên hệ thống của người dùng,
    giải mã cookies của Douyin bằng khóa AES Master Key giải mã qua DPAPI,
    và xuất ra tệp douyin_cookies.txt dạng Netscape để yt-dlp vượt rào cản.
    """
    import os
    import json
    import sqlite3
    import shutil
    import base64
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def CryptUnprotectData(encrypted_bytes):
        in_blob = DATA_BLOB()
        in_blob.cbData = len(encrypted_bytes)
        in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_char))
        out_blob = DATA_BLOB()
        res = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        )
        if not res:
            raise ctypes.WinError()
        decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
        return decrypted_bytes

    try:
        user_profile = os.environ.get("USERPROFILE")
        user_data_dir = os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data")
        if not os.path.exists(user_data_dir):
            return False

        local_state_path = os.path.join(user_data_dir, "Local State")
        if not os.path.exists(local_state_path):
            return False

        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.loads(f.read())

        encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
        encrypted_key = base64.b64decode(encrypted_key_b64)
        aes_key = CryptUnprotectData(encrypted_key[5:])

        # Lấy danh sách toàn bộ các profiles
        profiles = ["Default"]
        for item in os.listdir(user_data_dir):
            if item.startswith("Profile "):
                profiles.append(item)

        from worker.config import BASE_DIR
        temp_cookies_db = os.path.join(BASE_DIR, "worker", "temp_assets", "chrome_cookies_harvest_temp.db")
        final_cookies_txt = os.path.join(BASE_DIR, "worker", "temp_assets", "douyin_cookies.txt")

        douyin_cookies_list = []
        for profile in profiles:
            cookies_path = os.path.join(user_data_dir, profile, "Network", "Cookies")
            if not os.path.exists(cookies_path):
                continue

            try:
                try:
                    shutil.copy2(cookies_path, temp_cookies_db)
                except Exception as copy_err:
                    # Fallback using CreateFileW share flags to bypass file lock
                    success_copy = copy_locked_file_windows(cookies_path, temp_cookies_db)
                    if not success_copy:
                        import subprocess
                        # Secondary fallback using Windows native copy tool
                        cmd_copy = f'cmd.exe /c copy /y "{cookies_path}" "{temp_cookies_db}"'
                        res = subprocess.run(cmd_copy, shell=True, capture_output=True, text=True)
                        if res.returncode != 0:
                            cmd_ps = f'powershell -Command "Copy-Item -Path \'{cookies_path}\' -Destination \'{temp_cookies_db}\' -Force"'
                            res_ps = subprocess.run(cmd_ps, shell=True, capture_output=True, text=True)
                            if res_ps.returncode != 0:
                                raise copy_err

                conn = sqlite3.connect(temp_cookies_db)
                cursor = conn.cursor()
                cursor.execute("SELECT host_key, name, path, is_secure, expires_utc, encrypted_value FROM cookies WHERE host_key LIKE '%douyin.com'")
                rows = cursor.fetchall()

                temp_list = []
                for host_key, name, path, is_secure, expires_utc, encrypted_value in rows:
                    if encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11"):
                        iv = encrypted_value[3:15]
                        ciphertext = encrypted_value[15:-16]
                        tag = encrypted_value[-16:]

                        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                        aesgcm = AESGCM(aes_key)
                        try:
                            decrypted_val = aesgcm.decrypt(iv, ciphertext + tag, None).decode("utf-8")
                        except Exception:
                            decrypted_val = ""
                    else:
                        try:
                            decrypted_val = CryptUnprotectData(encrypted_value).decode("utf-8")
                        except Exception:
                            decrypted_val = ""

                    if decrypted_val:
                        domain = host_key
                        flag = "TRUE" if domain.startswith(".") else "FALSE"
                        cookie_path = path
                        secure = "TRUE" if is_secure == 1 else "FALSE"
                        expires = expires_utc
                        if expires_utc > 0:
                            expires = int((expires_utc - 11644473600000000) / 1000000)
                        temp_list.append((domain, flag, cookie_path, secure, expires, name, decrypted_val))

                if len(temp_list) > len(douyin_cookies_list):
                    douyin_cookies_list = temp_list

                conn.close()
                if os.path.exists(temp_cookies_db):
                    os.remove(temp_cookies_db)
            except Exception as ex:
                if "being used by another process" in str(ex) or "PermissionError" in type(ex).__name__ or (hasattr(ex, 'winerror') and ex.winerror == 32):
                    print(f"[Douyin Cookie Harvest Warning] Profile '{profile}' đang bị khóa bởi trình duyệt Chrome đang mở. Vui lòng tắt Chrome để thu hoạch cookies sạch!")
                else:
                    print(f"[Douyin Cookie Harvest Warning] Không thể xử lý Profile '{profile}': {ex}")
                if os.path.exists(temp_cookies_db):
                    try: os.remove(temp_cookies_db)
                    except Exception: pass

        if douyin_cookies_list:
            os.makedirs(os.path.dirname(final_cookies_txt), exist_ok=True)
            with open(final_cookies_txt, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# This is a generated file! Do not edit.\n\n")
                for domain, flag, path, secure, expires, name, value in douyin_cookies_list:
                    f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            print(f"[Douyin Cookie Harvest] Thu hoạch thành công {len(douyin_cookies_list)} cookies từ Chrome!")
            return True

        return False
    except Exception as e:
        print(f"[Douyin Cookie Harvest Warning] Lỗi khi thu hoạch cookies tự động: {e}")
        return False

def _get_ytdlp_cmd() -> list[str]:
    """Trả về lệnh gọi yt-dlp phù hợp tùy theo module python hoặc binary hệ thống"""
    import sys
    import shutil
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        ytdlp_bin = shutil.which("yt-dlp")
        if ytdlp_bin:
            return [ytdlp_bin]
        return [sys.executable, "-m", "yt_dlp"]


async def download_video_link(job_id: int, url: str, output_dir: str) -> tuple:
    """Tải video từ link mạng (YouTube/TikTok/Douyin) bằng yt-dlp và trích xuất tiêu đề"""
    import subprocess
    import uuid
    import re
    import os
    import sys

    is_douyin = "douyin.com" in url

    # Tự động chuẩn hóa và thu hoạch cookies sớm để phục vụ cho cả tiền kiểm tra (Pre-Validation) và tải về
    if is_douyin:
        match_modal = re.search(r"modal_id=(\d+)", url)
        match_vid = re.search(r"vid=(\d+)", url)
        video_id = match_modal.group(1) if match_modal else (match_vid.group(1) if match_vid else None)
        if video_id:
            url = f"https://www.douyin.com/video/{video_id}"
            print(f"[Python Worker] Chuẩn hóa link Douyin modal thành: {url}")

        # Thu hoạch cookies qua Playwright Stealth trước (để lấy cookies sạch không phụ thuộc DPAPI/v20)
        from worker.config import BASE_DIR
        profile_dir = os.path.join(BASE_DIR, "worker", f"chrome_profile_{job_id}")
        try:
            print(f"[Python Worker] Đang tự động nạp cookies Douyin qua Playwright guest session...")
            await asyncio.to_thread(harvest_cookies_via_playwright_sync, url, profile_dir)
        except Exception as pe:
            print(f"[Python Worker Warning] Thất bại khi nạp cookies qua Playwright guest session: {pe}. Thử thu hoạch từ Chrome profile...")
            # Fallback thu hoạch từ Chrome profile
            has_cookies = harvest_chrome_douyin_cookies()
            if not has_cookies:
                print("[Python Worker Warning] Không tìm thấy cookies Douyin trong trình duyệt Chrome của bạn.")
                print("[Yêu cầu hành động] Vui lòng mở trình duyệt Google Chrome thông thường, truy cập vào trang https://www.douyin.com một lần rồi chạy lại tiến trình RENDER!")

    # ─────────────────────────────────────────────────────────────────
    # PRE-VALIDATION LAYER — Tiền kiểm tra siêu nhẹ trước Playwright
    # Chạy yt-dlp --simulate để phân loại link trong < 1.5 giây.
    # Chặn hoàn toàn: Livestream, Album ảnh/Playlist, và link chết.
    # ─────────────────────────────────────────────────────────────────
    print(f"[Pre-Validation] Đang kiểm tra tính hợp lệ của link: {url}")
    cmd_check = _get_ytdlp_cmd() + ["--simulate", "--skip-download"]
    if is_douyin:
        from worker.config import BASE_DIR
        cookies_path = os.path.join(BASE_DIR, "worker", "temp_assets", "douyin_cookies.txt")
        if os.path.exists(cookies_path):
            cmd_check.extend(["--cookies", cookies_path])
    cmd_check.append(url)

    try:
        proc_check = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd_check,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=1.5,
        )
        # Đặt timeout tổng thể cho cả quá trình communicate()
        try:
            _, stderr_check = await asyncio.wait_for(proc_check.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            # Nếu yt-dlp không phản hồi sau 15 giây, giả định link lỗi
            try:
                proc_check.kill()
            except Exception:
                pass
            raise RuntimeError("Đường link không hoạt động hoặc bị nền tảng chặn truy cập.")

        if proc_check.returncode != 0:
            err_text = stderr_check.decode(errors="ignore").lower()
            if "live" in err_text or "livestream" in err_text or "is live" in err_text:
                raise RuntimeError("Hệ thống từ chối xử lý đường link Livestream trực tiếp.")
            elif "playlist" in err_text or "album" in err_text:
                raise RuntimeError(
                    "Đường link thuộc dạng Album ảnh/Danh sách phát, không phải video đơn hợp lệ."
                )
            else:
                raise RuntimeError("Đường link không hoạt động hoặc bị nền tảng chặn truy cập.")

        print(f"[Pre-Validation] ✅ Link hợp lệ — kích hoạt pipeline chính.")

    except asyncio.TimeoutError:
        # Không kịp spawn tiến trình trong 1.5 giây (hệ thống quá tải)
        print("[Pre-Validation Warning] Không thể khởi động tiến trình kiểm tra trong 1.5 giây — bỏ qua Pre-Validation, tiếp tục pipeline.")
    except RuntimeError as r_err:
        if is_douyin:
            print(f"[Pre-Validation Warning] Douyin pre-validation failed ({r_err}). Tiếp tục pipeline chính để Playwright / yt-dlp thu hoạch stream...")
        else:
            raise
    except Exception as pre_err:
        # Các lỗi bất ngờ trong Pre-Validation không được làm gián đoạn pipeline
        print(f"[Pre-Validation Warning] Lỗi không xác định khi kiểm tra link: {pre_err}. Tiếp tục pipeline.")

    # ─────────────────────────────────────────────────────────────────
    # Xử lý chuẩn hóa và trích xuất link stream trực tiếp cho Douyin
    # ─────────────────────────────────────────────────────────────────
    original_title = None
    direct_stream_downloaded = False
    if is_douyin:
        is_douyin_note = "/note/" in url
        if is_douyin_note:
            print(f"[Python Worker] Phát hiện link Douyin Note (slideshow). Bỏ qua trích xuất Playwright stream URL, tải trực tiếp bằng yt-dlp...")
        else:
            print(f"[Python Worker] Phát hiện link Douyin. Đang tự động trích xuất stream trực tiếp qua Stealth Playwright...")
            try:
                from worker.config import BASE_DIR
                profile_dir = os.path.join(BASE_DIR, "worker", f"chrome_profile_{job_id}")

                # Chạy hàm sync trích xuất trong luồng phụ (thread) để không chặn event loop
                extracted_url = await asyncio.to_thread(extract_douyin_video_sync, url, profile_dir)
                print(f"[Python Worker] Trích xuất thành công! Stream URL: {extracted_url[:100]}...")
                url = extracted_url

                # Tải video trực tiếp từ stream URL đã trích xuất qua HTTP GET để không phụ thuộc yt-dlp cookies
                if "http://" in url or "https://" in url:
                    output_filename = f"dub_source_{uuid.uuid4().hex}.mp4"
                    output_path = os.path.join(output_dir, output_filename)
                    try:
                        print(f"[Python Worker] Tải video Douyin trực tiếp từ CDN Stream URL...")
                        import urllib.request
                        req = urllib.request.Request(url, headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                            "Referer": "https://www.douyin.com/"
                        })
                        with urllib.request.urlopen(req, timeout=30) as resp, open(output_path, "wb") as f_out:
                            f_out.write(resp.read())
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            print(f"[Python Worker] ✅ Tải video Douyin trực tiếp từ CDN thành công! File: {output_path}")
                            return output_path, original_title or "Video Douyin"
                    except Exception as direct_err:
                        print(f"[Python Worker Warning] Tải trực tiếp từ CDN URL thất bại: {direct_err}. Thử chuyển sang yt-dlp...")
            except Exception as e:
                print(f"[Python Worker Warning] Thất bại khi trích xuất qua Playwright ({e}). Sẽ thử tải trực tiếp bằng yt-dlp...")


    # Thử lấy tiêu đề gốc của video trước qua yt-dlp
    sub_env = {**os.environ, "TEMP": output_dir, "TMP": output_dir, "TMPDIR": output_dir}
    try:
        cmd_title = _get_ytdlp_cmd() + ["--no-warnings", "--paths", f"temp:{output_dir}", "--get-title"]
        if is_douyin:
            from worker.config import BASE_DIR
            cookies_path = os.path.join(BASE_DIR, "worker", "temp_assets", "douyin_cookies.txt")
            if os.path.exists(cookies_path):
                cmd_title.extend(["--cookies", cookies_path])
        cmd_title.append(url)

        proc_title = await asyncio.create_subprocess_exec(
            *cmd_title,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=sub_env
        )
        stdout_t, stderr_t = await proc_title.communicate()
        if proc_title.returncode == 0:
            original_title = stdout_t.decode(errors='ignore').strip()
            print(f"[Python Worker] Đã trích xuất tiêu đề video gốc qua yt-dlp: '{original_title}'")
    except Exception as te:
        print(f"[Python Worker Warning] Không thể lấy tiêu đề video qua yt-dlp: {te}")

    output_filename = f"dub_source_{uuid.uuid4().hex}.mp4"
    output_path = os.path.join(output_dir, output_filename)

    cmd = _get_ytdlp_cmd() + [
        "--no-warnings",
        "--paths", f"temp:{output_dir}",
        "-f", "mp4",
        "-o", output_path
    ]

    # Nếu là Douyin, đính kèm file cookies.txt thu hoạch từ Playwright để yt-dlp vượt rào cản
    if is_douyin:
        from worker.config import BASE_DIR
        cookies_path = os.path.join(BASE_DIR, "worker", "temp_assets", "douyin_cookies.txt")
        if os.path.exists(cookies_path):
            print(f"[Python Worker] Đang tải Douyin qua yt-dlp sử dụng cookies sạch vừa thu hoạch...")
            cmd.extend(["--cookies", cookies_path])

    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=sub_env
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Lỗi tải video bằng yt-dlp: {stderr.decode(errors='ignore')}")
    return output_path, original_title
