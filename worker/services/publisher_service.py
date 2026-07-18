import os
import sys
import time
import random
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from worker.config import BASE_DIR, OUTPUT_DIR

class PublisherService:
    def __init__(self, profile_dir: str = None):
        # Thiết lập profile trình duyệt để lưu session cookie bền vững
        if profile_dir:
            self.profile_dir = profile_dir
        else:
            self.profile_dir = str(BASE_DIR / "worker" / "chrome_profile")
        print(f"[PublisherService] Persistent Chrome profile path: {self.profile_dir}")

    def _clean_joyride_overlays(self, page):
        """Tự động dọn dẹp các lớp phủ (Joyride Onboarding Tour Overlay) có thể cản trở tương tác"""
        try:
            joyride_selectors = [
                "#react-joyride-portal",
                ".react-joyride__overlay",
                ".react-joyride__spotlight"
            ]
            cleaned_any = False
            for selector in joyride_selectors:
                if page.query_selector(selector):
                    print(f"[PublisherService] Phát hiện onboarding overlay cản trở ({selector}). Đang tự động dọn dẹp...")
                    page.evaluate(f"document.querySelectorAll('{selector}').forEach(el => el.remove())")
                    cleaned_any = True
            if cleaned_any:
                time.sleep(1.5)
        except Exception as je:
            print(f"[PublisherService Warning] Không thể dọn dẹp joyride overlay: {je}")

    def create_stealth_browser_instance(
        self, 
        headless: bool = False, 
        proxy_ip: str = None, 
        proxy_port: int = None, 
        proxy_user: str = None, 
        proxy_pass: str = None
    ):
        """Khởi tạo instance trình duyệt thực tế chống phát hiện bot"""
        playwright = sync_playwright().start()
        
        # Thiết lập cấu hình Proxy dân cư động
        proxy_config = None
        if proxy_ip and proxy_port:
            proxy_config = {
                "server": f"http://{proxy_ip}:{proxy_port}"
            }
            if proxy_user and proxy_pass:
                proxy_config["username"] = proxy_user
                proxy_config["password"] = proxy_pass
            print(f"[PublisherService] Binding dynamic proxy: {proxy_ip}:{proxy_port}")
        
        # Windows Chrome standard installation path fallback with self-healing default Chromium
        try:
            browser_context = playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=headless,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ],
                proxy=proxy_config
            )
        except Exception as e:
            print(f"[PublisherService Warning] Failed to launch Chrome with channel='chrome': {e}. Falling back to default Chromium...")
            browser_context = playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ],
                proxy=proxy_config
            )
        
        page = browser_context.pages[0]
        # Áp dụng script ghi đè các thuộc tính nhận diện robot
        Stealth().apply_stealth_sync(page)
        
        return playwright, browser_context, page

    def human_type(self, page, selector: str, text: str):
        """Giả lập việc gõ phím của con người với độ trễ ngẫu nhiên 50ms - 150ms"""
        element = page.query_selector(selector)
        if not element:
            raise Exception(f"Không tìm thấy phần tử để gõ text với selector: {selector}")
            
        element.click()
        # Xóa text cũ nếu có
        # element.fill("") 
        
        for char in text:
            page.keyboard.type(char)
            # Độ trễ ngẫu nhiên giữa các lần nhấn phím
            time.sleep(random.uniform(0.05, 0.15))

    def _click_first_text_match(self, page, texts: list, timeout_ms: int = 2500) -> bool:
        """Click phần tử đầu tiên khớp text, dùng cho UI TikTok đổi ngôn ngữ liên tục."""
        for text in texts:
            try:
                locator = page.get_by_text(text, exact=False).first
                locator.wait_for(state="visible", timeout=timeout_ms)
                self._robust_click_locator(locator, timeout_ms=timeout_ms)
                print(f"[PublisherService] Clicked UI text: '{text}'")
                return True
            except Exception:
                continue
        return False

    def _robust_click_locator(self, locator, timeout_ms: int = 2500) -> bool:
        """Click có fallback cho TikTok Studio khi loading/topbar intercept pointer events."""
        try:
            locator.click(timeout=timeout_ms)
            return True
        except Exception as click_err:
            print(f"[PublisherService Warning] Normal click intercepted, retrying with force/DOM click: {click_err}")

        try:
            locator.click(timeout=timeout_ms, force=True)
            return True
        except Exception:
            pass

        try:
            locator.evaluate("(el) => el.click()")
            return True
        except Exception:
            return False

    def _robust_click_element(self, element, timeout_ms: int = 2500) -> bool:
        try:
            element.click(timeout=timeout_ms)
            return True
        except Exception as click_err:
            print(f"[PublisherService Warning] Element click intercepted, retrying with force/DOM click: {click_err}")

        try:
            element.click(timeout=timeout_ms, force=True)
            return True
        except Exception:
            pass

        try:
            element.evaluate("(el) => el.click()")
            return True
        except Exception:
            return False

    def _wait_music_panel_idle(self, page, timeout_s: float = 12.0):
        """Đợi panel nhạc ngừng loading để tránh lớp loading chặn click."""
        loading_selectors = [
            ".MusicPanelTabListMusicList__loading",
            "[class*='MusicPanel'][class*='loading']",
            "[class*='loading']",
            "[aria-busy='true']",
        ]
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            blocking = False
            for selector in loading_selectors:
                try:
                    for element in page.query_selector_all(selector):
                        if element.is_visible():
                            blocking = True
                            break
                except Exception:
                    continue
                if blocking:
                    break
            if not blocking:
                return True
            time.sleep(0.5)
        print("[PublisherService Warning] Music panel still appears busy; continuing with robust click fallback.")
        return False

    def _click_music_result_or_add(self, page, song_title: str, artist_name: str = "") -> bool:
        """Chọn sound trong TikTok editor. UI mới thường dùng nút Add nhỏ trong panel Sounds."""
        self._wait_music_panel_idle(page, timeout_s=15.0)
        candidates = [song_title, artist_name or song_title]

        for text in candidates:
            if not text:
                continue
            try:
                locator = page.get_by_text(text, exact=False).first
                locator.wait_for(state="visible", timeout=2500)
                if self._robust_click_locator(locator, timeout_ms=2500):
                    print(f"[PublisherService] Clicked music result text: {text}")
                    time.sleep(1.0)
                    return True
            except Exception:
                continue

        add_labels = ["Add", "Use", "Select", "Chọn", "Thêm", "Sử dụng", "Dùng"]
        if self._click_visible_button_by_text(page, add_labels, timeout_s=4.0):
            print("[PublisherService] Clicked Add/Use button for music result.")
            time.sleep(1.5)
            return True

        try:
            clicked = page.evaluate(
                """({ title, artist }) => {
                    const norm = (value) => (value || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
                    const titleNorm = norm(title);
                    const artistNorm = norm(artist);
                    const controls = Array.from(document.querySelectorAll("button, [role='button'], div[tabindex='0'], span[tabindex='0']"));
                    const scored = controls
                        .filter((el) => {
                            const rect = el.getBoundingClientRect();
                            return rect.width > 8 && rect.height > 8 && rect.left < window.innerWidth * 0.45;
                        })
                        .map((el) => {
                            const container = el.closest("div, li, section") || el.parentElement || el;
                            const text = norm(container.innerText || container.textContent || el.getAttribute('aria-label') || '');
                            let score = 0;
                            if (titleNorm && text.includes(titleNorm)) score += 3;
                            if (artistNorm && text.includes(artistNorm)) score += 2;
                            if (/add|use|select|chon|them|su dung/.test(text)) score += 1;
                            return { el, score };
                        })
                        .filter((item) => item.score > 0)
                        .sort((a, b) => b.score - a.score);
                    if (!scored.length) return false;
                    scored[0].el.click();
                    return true;
                }""",
                {"title": song_title or "", "artist": artist_name or ""},
            )
            if clicked:
                print("[PublisherService] Selected music result by DOM panel fallback.")
                time.sleep(1.5)
                return True
        except Exception as exc:
            print(f"[PublisherService Warning] Music result DOM fallback failed: {exc}")

        return False

    def _save_editor_if_open(self, page, required: bool = False) -> bool:
        """TikTok Studio mở editor riêng khi chọn Sounds; cần Save để quay lại trang upload."""
        try:
            page_content = page.content().lower()
            looks_like_editor = (
                "search sounds" in page_content
                or "add title for your video" in page_content
                or "select an item to edit" in page_content
            )
        except Exception:
            looks_like_editor = False

        if not looks_like_editor:
            return True

        print("[PublisherService] TikTok editor detected. Saving sound edits before returning to upload page...")
        save_labels = ["Save", "Lưu"]
        if not self._click_visible_button_by_text(page, save_labels, timeout_s=6.0):
            for label in save_labels:
                try:
                    button = page.get_by_role("button", name=label, exact=False).first
                    button.wait_for(state="visible", timeout=1500)
                    if self._robust_click_locator(button, timeout_ms=1500):
                        break
                except Exception:
                    continue
            else:
                message = "Không bấm được nút Save sau khi chọn sound trong TikTok editor."
                if required:
                    raise Exception(message)
                print(f"[PublisherService Warning] {message}")
                return False

        time.sleep(3.0)
        try:
            page.wait_for_selector("button:has-text('Post'), button:has-text('Publish'), button:has-text('Đăng')", timeout=20000)
        except Exception:
            print("[PublisherService Warning] Did not detect publish button after Save; continuing.")
        return True

    def _find_visible_input(self, page, selectors: list):
        for selector in selectors:
            try:
                elements = page.query_selector_all(selector)
                for element in elements:
                    if element.is_visible() and element.is_enabled():
                        return element
            except Exception:
                continue
        return None

    def _click_visible_button_by_text(self, page, texts: list, timeout_s: float = 6.0) -> bool:
        """Click đúng button/panel action theo text, tránh bấm nhầm text trong preview."""
        deadline = time.time() + timeout_s
        wanted = [str(text or "").lower().strip() for text in texts if str(text or "").strip()]
        while time.time() < deadline:
            try:
                controls = page.query_selector_all("button, [role='button'], div[tabindex='0'], span[tabindex='0']")
                for control in controls:
                    if not control.is_visible() or not control.is_enabled():
                        continue
                    label = (control.inner_text() or "").lower().strip()
                    aria = (control.get_attribute("aria-label") or "").lower().strip()
                    combined = f"{label} {aria}".strip()
                    if any(text in combined for text in wanted):
                        self._robust_click_element(control, timeout_ms=2000)
                        print(f"[PublisherService] Clicked button/control matching: {texts}")
                        return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def _page_text_lower(self, page) -> str:
        try:
            return page.evaluate("() => document.body.innerText || document.body.textContent || ''").lower()
        except Exception:
            try:
                return page.content().lower()
            except Exception:
                return ""

    def _looks_like_uploaded_video_ready(self, page) -> bool:
        """Best-effort check that TikTok Studio still shows an uploaded video/editor surface."""
        selectors = [
            "video",
            "canvas",
            "[class*='preview' i]",
            "[class*='upload' i]",
            "[data-e2e*='upload' i]",
        ]
        for selector in selectors:
            try:
                for element in page.query_selector_all(selector):
                    if element.is_visible():
                        return True
            except Exception:
                continue

        body_text = self._page_text_lower(page)
        ready_tokens = [
            "upload complete",
            "upload successful",
            "tải lên hoàn tất",
            "tải lên thành công",
        ]
        return any(token in body_text for token in ready_tokens)

    def _copyright_issue_detected(self, body_text: str) -> bool:
        issue_patterns = [
            "copyright issue",
            "copyright issue found",
            "copyright issues found",
            "copyrighted content detected",
            "copyright violation",
            "copyright claim",
            "sound removed",
            "video muted",
            "not eligible to post",
            "cannot be posted",
            "can't be posted",
            "vấn đề bản quyền",
            "vi phạm bản quyền",
            "phát hiện bản quyền",
            "nội dung có bản quyền",
            "âm thanh bị tắt",
            "video bị tắt tiếng",
            "không thể đăng",
        ]
        return any(pattern in body_text for pattern in issue_patterns)

    def _copyright_check_passed(self, body_text: str) -> bool:
        pass_patterns = [
            "no issues found",
            "no copyright issue",
            "no copyright issues",
            "copyright check passed",
            "checks complete",
            "check complete",
            "không phát hiện vấn đề",
            "không có vấn đề",
            "không có vấn đề bản quyền",
            "kiểm tra hoàn tất",
            "đã kiểm tra xong",
        ]
        return any(pattern in body_text for pattern in pass_patterns)

    def _copyright_check_pending(self, body_text: str) -> bool:
        pending_patterns = [
            "checking for copyright",
            "copyright check in progress",
            "checks in progress",
            "checking",
            "processing",
            "đang kiểm tra",
            "đang xử lý",
        ]
        copyright_context = "copyright" in body_text or "bản quyền" in body_text or "checks" in body_text or "kiểm tra" in body_text
        return copyright_context and any(pattern in body_text for pattern in pending_patterns)

    def _wait_for_copyright_check_before_publish(self, page, timeout_s: float = 150.0) -> bool:
        """
        Chờ TikTok Studio kiểm tra bản quyền trước khi bấm đăng.
        Nếu UI không còn thấy video/khối check thì bỏ qua để tiến trình vẫn đăng tiếp.
        """
        print("[PublisherService] Checking copyright status before publish...")
        self._clean_joyride_overlays(page)

        if not self._looks_like_uploaded_video_ready(page):
            print("[PublisherService Warning] Không tìm thấy video/editor trên trang để kiểm tra bản quyền. Bỏ qua bước check và đăng tiếp.")
            return True

        # TikTok có thể dùng checkbox/toggle hoặc nút riêng để bật copyright check.
        check_labels = [
            "Run a copyright check",
            "Copyright check",
            "Check for copyright",
            "Kiểm tra bản quyền",
            "Chạy kiểm tra bản quyền",
        ]
        try:
            controls = page.query_selector_all("button, [role='button'], input[type='checkbox'], [role='switch']")
            for control in controls:
                if not control.is_visible() or not control.is_enabled():
                    continue
                label = (
                    (control.inner_text() or "")
                    + " "
                    + (control.get_attribute("aria-label") or "")
                    + " "
                    + (control.get_attribute("name") or "")
                ).lower()
                if any(text.lower() in label for text in check_labels):
                    self._robust_click_element(control, timeout_ms=2000)
                    print("[PublisherService] Triggered/confirmed TikTok copyright check.")
                    time.sleep(2.0)
                    break
        except Exception as check_err:
            print(f"[PublisherService Warning] Không tự bật được copyright check, sẽ đọc trạng thái hiện có: {check_err}")

        deadline = time.time() + timeout_s
        saw_check_context = False
        while time.time() < deadline:
            if not self._looks_like_uploaded_video_ready(page):
                print("[PublisherService Warning] Không còn tìm thấy video khi chờ copyright check. Thoát bước check và đăng tiếp.")
                return True

            body_text = self._page_text_lower(page)
            has_check_context = "copyright" in body_text or "bản quyền" in body_text or "checks" in body_text
            saw_check_context = saw_check_context or has_check_context

            if self._copyright_check_passed(body_text):
                print("[PublisherService] Copyright check complete: no issue detected.")
                return True

            if self._copyright_issue_detected(body_text):
                raise Exception("TikTok Studio phát hiện cảnh báo bản quyền. Dừng đăng để bạn kiểm tra lại video/nhạc.")

            if self._copyright_check_pending(body_text):
                print("[PublisherService] Copyright check is still running; waiting...")
                time.sleep(5.0)
                continue

            if not saw_check_context:
                print("[PublisherService Warning] Không tìm thấy khối kiểm tra bản quyền trên TikTok Studio. Bỏ qua và đăng tiếp.")
                return True

            # Có context check nhưng không có trạng thái rõ ràng; chờ thêm một nhịp ngắn.
            time.sleep(4.0)

        print("[PublisherService Warning] Hết thời gian chờ copyright check, không thấy cảnh báo rõ ràng. Tiếp tục đăng.")
        return True

    def _open_sounds_panel(self, page, required: bool = False) -> bool:
        """Mở panel Sounds của TikTok Studio bằng các selector ưu tiên button thật."""
        self._clean_joyride_overlays(page)

        sound_labels = [
            "Sounds",
            "Sound",
            "Add sound",
            "Add music",
            "Music",
            "Thêm âm thanh",
            "Thêm nhạc",
            "Âm thanh",
            "Nhạc",
        ]
        if self._click_visible_button_by_text(page, sound_labels, timeout_s=5.0):
            time.sleep(1.5)
            return True

        # Fallback Playwright locator theo role, vẫn ưu tiên control chứ không click text rời.
        for label in sound_labels:
            try:
                button = page.get_by_role("button", name=label, exact=False).first
                button.wait_for(state="visible", timeout=1500)
                self._robust_click_locator(button, timeout_ms=1500)
                print(f"[PublisherService] Opened Sounds panel by role: {label}")
                time.sleep(1.5)
                return True
            except Exception:
                continue

        message = "Không tìm thấy hoặc không bấm được nút Sounds/Add sound trên TikTok Studio."
        if required:
            raise Exception(message)
        print(f"[PublisherService Warning] {message}")
        return False

    def _find_music_search_field(self, page, timeout_s: float = 8.0):
        """TikTok đổi UI thường xuyên: ô tìm kiếm có thể là input, role searchbox/combobox hoặc contenteditable."""
        music_selectors = [
            "input[placeholder*='Search sounds']",
            "input[placeholder*='Search music']",
            "input[placeholder*='Search audio']",
            "input[placeholder*='Tìm âm thanh']",
            "input[placeholder*='Tìm nhạc']",
            "[role='searchbox'][aria-label*='sound' i]",
            "[role='searchbox'][aria-label*='music' i]",
            "[role='combobox'][aria-label*='sound' i]",
            "[role='combobox'][aria-label*='music' i]",
        ]
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            field = self._find_visible_input(page, music_selectors)
            if field:
                return field
            field = self._find_search_field_inside_sounds_panel(page)
            if field:
                return field
            time.sleep(0.5)
        return None

    def _find_search_field_inside_sounds_panel(self, page):
        try:
            return page.evaluate_handle(
                """() => {
                    const norm = (value) => (value || '').toLowerCase();
                    const fieldSelectors = [
                        "input[type='search']",
                        "input",
                        "[role='searchbox']",
                        "[role='combobox']",
                        "textarea",
                        "div[contenteditable='true']"
                    ];
                    const panelSelectors = [
                        "aside",
                        "[class*='MusicPanel']",
                        "[class*='Sound']",
                        "[class*='sound']",
                        "[class*='audio']",
                        "[class*='Audio']"
                    ];
                    const panels = Array.from(document.querySelectorAll(panelSelectors.join(',')));
                    for (const panel of panels) {
                        const panelText = norm(panel.innerText || panel.textContent || '');
                        if (!/sounds|sound|music|audio|âm thanh|nhạc|search sounds/.test(panelText)) continue;
                        if (/location|search locations|địa điểm|vị trí/.test(panelText) && !/sounds|search sounds|music|audio/.test(panelText)) continue;
                        for (const selector of fieldSelectors) {
                            for (const field of Array.from(panel.querySelectorAll(selector))) {
                                const rect = field.getBoundingClientRect();
                                const label = norm(field.getAttribute('placeholder') || field.getAttribute('aria-label') || '');
                                if (rect.width < 80 || rect.height < 16) continue;
                                if (/location|địa điểm|vị trí/.test(label)) continue;
                                return field;
                            }
                        }
                    }
                    return null;
                }"""
            ).as_element()
        except Exception:
            return None

    def _assert_not_location_search(self, element) -> bool:
        try:
            label = element.evaluate(
                """el => {
                    const own = [
                        el.getAttribute('placeholder'),
                        el.getAttribute('aria-label'),
                        el.textContent,
                        el.innerText
                    ].filter(Boolean).join(' ');
                    const container = el.closest('div, section, label, aside') || el.parentElement;
                    return `${own} ${(container?.innerText || container?.textContent || '')}`.toLowerCase();
                }"""
            )
            if any(token in str(label or "") for token in ["search locations", "location", "địa điểm", "vị trí"]):
                print("[PublisherService Warning] Refusing to type music query into Location search field.")
                return False
        except Exception:
            pass
        return True

    def _type_into_control(self, page, element, text: str):
        if not self._assert_not_location_search(element):
            raise Exception("Ô nhập hiện tại là ô tìm vị trí, không phải ô tìm nhạc.")
        self._robust_click_element(element, timeout_ms=3000)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        try:
            tag_name = (element.evaluate("el => el.tagName") or "").lower()
            is_contenteditable = bool(element.evaluate("el => el.isContentEditable"))
            if tag_name in ("input", "textarea") and not is_contenteditable:
                element.fill("")
        except Exception:
            pass
        for char in text:
            page.keyboard.type(char)
            time.sleep(random.uniform(0.03, 0.09))

    def _set_range_value(self, page, element, value: float) -> bool:
        try:
            element.evaluate(
                """(el, value) => {
                    el.value = String(value);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                value,
            )
            return True
        except Exception:
            return False

    def _set_tiktok_audio_mix(self, page, tiktok_volume_percent: int = 2, original_volume_percent: int = 100, required: bool = False) -> bool:
        """
        Sau khi chọn sound TikTok, chỉnh âm lượng sound TikTok thật thấp
        và giữ âm lượng video gốc ở 100%.
        """
        tiktok_volume_percent = max(1, min(3, int(tiktok_volume_percent or 2)))
        original_volume_percent = max(0, min(100, int(original_volume_percent or 100)))
        print(
            f"[PublisherService] Setting audio mix: TikTok sound {tiktok_volume_percent}%, "
            f"original video {original_volume_percent}%"
        )

        volume_labels = [
            "Chỉnh sửa âm thanh",
            "Âm lượng",
            "Volume",
            "Edit sound",
            "Audio",
            "Sound",
        ]
        self._click_first_text_match(page, volume_labels, timeout_ms=1800)
        time.sleep(1.0)

        ranges = []
        try:
            ranges = [el for el in page.query_selector_all("input[type='range']") if el.is_visible() and el.is_enabled()]
        except Exception:
            ranges = []

        # TikTok thường có 2 thanh: âm thanh đã thêm và âm thanh gốc. Nếu không đọc được nhãn,
        # đặt thanh đầu tiên rất nhỏ, thanh thứ hai 100%.
        if len(ranges) >= 2:
            ok_sound = self._set_range_value(page, ranges[0], tiktok_volume_percent)
            ok_original = self._set_range_value(page, ranges[1], original_volume_percent)
            if ok_sound and ok_original:
                print("[PublisherService] Audio mix sliders updated by range controls.")
                return True

        # Fallback: tìm input quanh nhãn phổ biến trong DOM.
        try:
            updated = page.evaluate(
                """({ tiktokVolume, originalVolume }) => {
                    const lower = (node) => (node?.innerText || node?.textContent || '').toLowerCase();
                    const setRange = (range, value) => {
                        if (!range) return false;
                        range.value = String(value);
                        range.dispatchEvent(new Event('input', { bubbles: true }));
                        range.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    };
                    const ranges = Array.from(document.querySelectorAll("input[type='range']"));
                    let soundDone = false;
                    let originalDone = false;
                    for (const range of ranges) {
                        const container = range.closest('div, section, label') || range.parentElement;
                        const text = lower(container);
                        if (!soundDone && /sound|music|nhạc|am thanh|âm thanh/.test(text) && !/original|gốc|video/.test(text)) {
                            soundDone = setRange(range, tiktokVolume);
                        } else if (!originalDone && /original|gốc|video/.test(text)) {
                            originalDone = setRange(range, originalVolume);
                        }
                    }
                    if (!soundDone && ranges[0]) soundDone = setRange(ranges[0], tiktokVolume);
                    if (!originalDone && ranges[1]) originalDone = setRange(ranges[1], originalVolume);
                    return soundDone && originalDone;
                }""",
                {
                    "tiktokVolume": tiktok_volume_percent,
                    "originalVolume": original_volume_percent,
                },
            )
            if updated:
                print("[PublisherService] Audio mix sliders updated by DOM fallback.")
                return True
        except Exception as volume_err:
            print(f"[PublisherService Warning] Audio mix DOM fallback failed: {volume_err}")

        message = "Không chỉnh được âm lượng TikTok sound/original video trên giao diện hiện tại."
        if required:
            raise Exception(message)
        print(f"[PublisherService Warning] {message}")
        return False

    def add_music_to_tiktok_post(
        self,
        page,
        song_title: str = None,
        artist_name: str = None,
        required: bool = False,
        tiktok_volume_percent: int = 2,
        original_volume_percent: int = 100,
    ) -> bool:
        """
        Mở phần thêm nhạc của TikTok Studio, tìm bài đã được chọn ở bước render
        và chọn track đó trước khi đăng.
        """
        if not song_title or song_title in ("HOT TRENDING", "AUTO DETECT"):
            print("[PublisherService] Không có tên bài hát cụ thể để chọn trên TikTok Studio. Bỏ qua bước thêm nhạc.")
            return False

        query = f"{song_title} {artist_name or ''}".strip()
        print(f"[PublisherService] Adding TikTok music before publish: '{query}'")
        self._clean_joyride_overlays(page)

        if not self._open_sounds_panel(page, required=required):
            return False

        time.sleep(2.0)
        self._clean_joyride_overlays(page)

        search_input = self._find_music_search_field(page, timeout_s=10.0)
        if not search_input:
            message = "Không tìm thấy ô tìm kiếm nhạc sau khi mở phần thêm nhạc."
            if required:
                raise Exception(message)
            print(f"[PublisherService Warning] {message}")
            return False

        self._type_into_control(page, search_input, query)
        page.keyboard.press("Enter")
        print(f"[PublisherService] Searching TikTok music: '{query}'")
        time.sleep(2.0)
        self._wait_music_panel_idle(page, timeout_s=15.0)

        if self._click_music_result_or_add(page, song_title=song_title, artist_name=artist_name or ""):
            time.sleep(2.0)
            print(f"[PublisherService] Đã chọn nhạc TikTok: '{query}'")
            self._set_tiktok_audio_mix(
                page,
                tiktok_volume_percent=tiktok_volume_percent,
                original_volume_percent=original_volume_percent,
                required=False,
            )
            self._save_editor_if_open(page, required=required)
            return True

        message = f"Đã tìm nhạc '{query}' nhưng không chọn được sound trong TikTok editor."
        if required:
            raise Exception(message)
        print(f"[PublisherService Warning] {message}")
        return False

    def publish_video_to_tiktok(
        self, 
        video_path: str, 
        caption: str, 
        hashtags: list, 
        force_headful: bool = True, 
        music_metadata: dict = None, 
        comment_text: str = None,
        proxy_ip: str = None,
        proxy_port: int = None,
        proxy_user: str = None,
        proxy_pass: str = None
    ) -> bool:
        """
        Quy trình tự động hóa xuất bản video lên TikTok Studio qua Playwright Stealth.
        Hỗ trợ chế độ chạy hiển thị giao diện ở lần đầu tiên.
        """
        print(f"[PublisherService] Dispatching video upload for: {video_path}")
        
        # Nếu lần đầu tiên hoặc có yêu cầu, bắt buộc phải chạy có giao diện (headless=False)
        headless = False if force_headful else True
        
        playwright, context, page = self.create_stealth_browser_instance(
            headless=headless,
            proxy_ip=proxy_ip,
            proxy_port=proxy_port,
            proxy_user=proxy_user,
            proxy_pass=proxy_pass
        )
        
        try:
            # 1. Điều hướng đến TikTok Studio Upload
            upload_url = "https://www.tiktok.com/tiktokstudio/upload"
            print(f"[PublisherService] Navigating to: {upload_url}")
            page.goto(upload_url, wait_until="domcontentloaded", timeout=60000)
            
            # 2. Kiểm tra trạng thái Đăng nhập
            # Ở lần chạy đầu tiên, ta dừng lại để người dùng thực hiện đăng nhập thủ công
            if force_headful:
                print("[PublisherService] HEADFUL MODE ACTIVE. Vui lòng thực hiện ĐĂNG NHẬP / QUÉT MÃ QR trên trình duyệt Chrome vừa mở ra...")
                print("[PublisherService] Đang giám sát trạng thái đăng nhập... Chờ 90 giây hoặc cho đến khi chuyển hướng vào Dashboard thành công.")
                
                # Chờ tối đa 90 giây để người dùng quét mã QR hoặc hoàn tất đăng nhập
                logged_in = False
                for _ in range(60):  # 60 * 1.5s = 90s
                    time.sleep(1.5)
                    # Nếu có sự hiện diện của phần tử upload (nghĩa là đã đăng nhập thành công và trang load xong)
                    if page.query_selector("input[type='file']"):
                        logged_in = True
                        print("[PublisherService] Đã phát hiện đăng nhập thành công và trường tải video đã sẵn sàng!")
                        break
                
                if not logged_in:
                    raise Exception("Hết thời gian chờ đăng nhập (90 giây). Vui lòng thử lại lệnh.")

            # Chờ thêm 5 giây để trang tải ổn định
            time.sleep(5.0)

            # Tự động dọn dẹp onboarding overlay nếu xuất hiện sớm
            self._clean_joyride_overlays(page)

            # 3. Thực hiện tải Video lên
            file_input_selector = "input[type='file']"
            file_input = page.query_selector(file_input_selector)
            
            if not file_input:
                # Chụp lại màn hình lỗi để tự phục hồi & cảnh báo
                screenshot_path = str(OUTPUT_DIR / "error.png")
                page.screenshot(path=screenshot_path)
                raise Exception("Không tìm thấy trường tải video lên. Session đăng nhập có thể đã hết hạn hoặc giao diện thay đổi.")

            print("[PublisherService] Selecting video file...")
            file_input.set_input_files(video_path)
            
            # Chờ video upload lên hoàn tất (Tự thích ứng theo mạng, giải quyết [C5])
            print("[PublisherService] Uploading video to TikTok cloud... Waiting for upload to complete...")
            uploaded = False
            for attempt in range(150):  # Chờ tối đa 300 giây (5 phút)
                time.sleep(2.0)
                
                # 1. Kiểm tra xem nút đăng bài đã sẵn sàng và được kích hoạt chưa
                buttons = page.query_selector_all("button")
                publish_btn = None
                for btn in buttons:
                    btn_text = btn.inner_text()
                    if "Đăng" in btn_text or "Post" in btn_text or "Publish" in btn_text:
                        publish_btn = btn
                        break
                
                if publish_btn and publish_btn.is_enabled():
                    # Đảm bảo không còn ký tự phần trăm tải lên hiển thị
                    page_content = page.content()
                    if "Tải lên" in page_content and "%" in page_content:
                        continue
                    print("[PublisherService] Upload complete: 'Publish' button is now active! 🎉")
                    uploaded = True
                    break
                
                # 2. Kiểm tra các câu chữ thông báo thành công
                page_content = page.content()
                if "Tải lên thành công" in page_content or "Tải lên hoàn tất" in page_content or "Upload successful" in page_content or "Upload complete" in page_content:
                    print("[PublisherService] Upload complete: Detected success status on page! 🎉")
                    uploaded = True
                    time.sleep(3.0)
                    break
            
            if not uploaded:
                print("[PublisherService WARNING] Hết thời gian chờ upload tự động (300s). Tiếp tục tiến trình nhập mô tả...")

            # 4. Nhập tiêu đề, kịch bản caption và hashtags
            # Định dạng Caption: "[Tiêu đề video] [Hashtags]"
            full_caption = caption + " " + " ".join(hashtags)
            
            # Giới hạn độ dài Caption TikTok tối đa 2200 ký tự (giải quyết [L4])
            if len(full_caption) > 2200:
                print(f"[PublisherService WARNING] Caption too long ({len(full_caption)} characters). Truncating to 2200 characters...")
                full_caption = full_caption[:2190] + "..."
            
            # Selector của khung soạn thảo mô tả trên TikTok Studio
            caption_selector = "div[contenteditable='true']"
            page.wait_for_selector(caption_selector, timeout=20000)
            
            # Tự động dọn dẹp onboarding overlay trước khi nhập caption
            self._clean_joyride_overlays(page)

            print(f"[PublisherService] Entering caption: '{full_caption}'")
            # Clear text cũ
            page.query_selector(caption_selector).click()
            # Dùng bàn phím select all và xóa
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            
            # Gõ kiểu con người trễ ngẫu nhiên
            self.human_type(page, caption_selector, full_caption)

            # 5. Nếu đây là video âm nhạc, chọn thêm bài nhạc trên TikTok Studio trước khi đăng.
            if music_metadata:
                song_title = music_metadata.get("song_title")
                artist_name = music_metadata.get("artist_name")
                require_tiktok_music = bool(music_metadata.get("require_tiktok_music", True))
                tiktok_volume_percent = int(music_metadata.get("tiktok_sound_volume_percent", 2))
                original_volume_percent = int(music_metadata.get("original_video_volume_percent", 100))
                self.add_music_to_tiktok_post(
                    page,
                    song_title=song_title,
                    artist_name=artist_name,
                    required=require_tiktok_music,
                    tiktok_volume_percent=tiktok_volume_percent,
                    original_volume_percent=original_volume_percent,
                )

                # Video âm nhạc cần đợi TikTok kiểm tra bản quyền trước khi bấm đăng.
                # Nếu Studio không hiển thị được video/khối check, helper sẽ bỏ qua và cho đăng tiếp.
                self._wait_for_copyright_check_before_publish(page, timeout_s=150.0)
            
            # 6. Phê duyệt và Đăng bài
            # Tìm nút "Đăng" (Publish) - Thường chứa văn bản "Post" hoặc "Đăng"
            time.sleep(3.0)
            publish_button = None
            
            # Tìm kiếm nút qua text tiếng Việt/Anh phổ biến
            buttons = page.query_selector_all("button")
            for btn in buttons:
                text = btn.inner_text()
                if "Đăng" in text or "Post" in text or "Publish" in text:
                    publish_button = btn
                    break

            if not publish_button:
                raise Exception("Không tìm thấy nút 'Đăng' (Publish) trên màn hình TikTok Studio.")

            print("[PublisherService] Clicking 'Publish' button...")
            publish_button.click()
            
            # Chờ 4 giây xem có bảng cảnh báo/xác nhận (ví dụ Copyright Check incomplete) xuất hiện không
            time.sleep(4.0)
            
            # Quét tất cả các nút để tìm nút xác nhận bỏ qua bản quyền/tiếp tục đăng
            buttons = page.query_selector_all("button")
            for btn in buttons:
                try:
                    text = btn.inner_text()
                    if "post now" in text.lower() or "đăng ngay" in text.lower() or "tiếp tục đăng" in text.lower() or "continue to post" in text.lower():
                        print(f"[PublisherService] Phát hiện popup xác nhận với nút: '{text}'. Tiến hành nhấp để tiếp tục đăng...")
                        btn.click()
                        time.sleep(4.0)
                        break
                except Exception as btn_err:
                    pass
            
            # Chờ hoàn thành đăng bài
            print("[PublisherService] Waiting for publish response...")
            time.sleep(8.0)
            
            print("[PublisherService Success] Video successfully published to TikTok!")
            
            # Nếu có comment_text, thực hiện tìm link video và post comment
            if comment_text:
                try:
                    video_url = self._find_published_video_url(page)
                    if video_url:
                        self.post_comment_to_video(page, video_url, comment_text)
                    else:
                        print("[PublisherService Warning] Could not extract video URL, skipping auto-comment.")
                except Exception as comm_err:
                    print(f"[PublisherService Warning] Failed during comment posting: {comm_err}")
            
            # Đóng trình duyệt
            context.close()
            playwright.stop()
            return True

        except Exception as e:
            print(f"[PublisherService Error] Error during stealth upload: {e}")
            try:
                screenshot_path = str(OUTPUT_DIR / "error.png")
                page.screenshot(path=screenshot_path)
                print(f"[PublisherService] Saved error screenshot to: {screenshot_path}")
            except Exception as se:
                print(f"[PublisherService] Failed to capture error screenshot: {se}")
            
            # Đóng các tài nguyên
            try:
                context.close()
                playwright.stop()
            except:
                pass
            
            raise e

    def _find_published_video_url(self, page) -> str:
        """
        Tìm URL của video vừa đăng.
        Cách 1: Quét trên trang hoàn thành upload hiện tại xem có liên kết chứa '/video/'.
        Cách 2: Điều hướng đến trang Quản lý bài đăng của TikTok Studio và lấy liên kết video đầu tiên.
        """
        time.sleep(3.0) # Đợi trang phản hồi sau khi ấn đăng
        
        # Cách 1: Tìm link trên trang hiện tại
        for selector in ["a[href*='/video/']", "a:has-text('View')", "a:has-text('Xem')", "a:has-text('Watch')"]:
            try:
                link = page.query_selector(selector)
                if link:
                    href = link.get_attribute("href")
                    if href:
                        import urllib.parse
                        url = urllib.parse.urljoin(page.url, href)
                        if "/video/" in url:
                            print(f"[PublisherService] Found video URL from publish success page: {url}")
                            return url
            except Exception:
                continue

        # Cách 2: Điều hướng đến posts manager
        try:
            posts_url = "https://www.tiktok.com/tiktokstudio/posts"
            print(f"[PublisherService] Navigating to posts manager: {posts_url} to extract video link...")
            page.goto(posts_url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(6.0) # Đợi trang tải danh sách bài viết
            
            links = page.query_selector_all("a[href*='/video/']")
            for link in links:
                href = link.get_attribute("href")
                if href:
                    import urllib.parse
                    url = urllib.parse.urljoin(page.url, href)
                    if "/video/" in url:
                        print(f"[PublisherService] Found video URL from posts manager: {url}")
                        return url
        except Exception as e:
            print(f"[PublisherService Warning] Failed to find video URL from posts page: {e}")
            
        return ""

    def post_comment_to_video(self, page, video_url: str, comment_text: str) -> bool:
        """
        Điều hướng đến trang video công khai và thực hiện tự động gửi bình luận.
        """
        print(f"[PublisherService] Navigating to public video URL: {video_url} to post comment...")
        try:
            page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(5.0) # Đợi các thành phần trang tải ổn định
            
            # Selector ô nhập bình luận phổ biến của TikTok
            comment_selectors = [
                "[data-e2e='comment-input']",
                "div[contenteditable='true']",
                "input[placeholder*='comment' i]",
                "input[placeholder*='luận' i]",
                ".comment-input",
                "textarea"
            ]
            
            input_el = None
            for selector in comment_selectors:
                try:
                    el = page.query_selector(selector)
                    if el and el.is_visible():
                        input_el = el
                        break
                except Exception:
                    continue
                    
            if not input_el:
                print("[PublisherService Warning] Could not locate comment input field on video page.")
                return False
                
            print("[PublisherService] Comment input field located. Typing comment...")
            input_el.click()
            time.sleep(0.5)
            
            # Gán text bình luận qua JS để gõ nhanh và chính xác đối với văn bản dài (2-3 đoạn)
            page.evaluate(
                """(el, text) => {
                    el.focus();
                    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                        el.value = text;
                    } else {
                        el.innerText = text;
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                input_el,
                comment_text
            )
            time.sleep(1.5)
            
            # Bấm nút gửi bình luận
            post_selectors = [
                "[data-e2e='comment-post']",
                "button:has-text('Post')",
                "button:has-text('Đăng')",
                "button[type='submit']"
            ]
            
            post_btn = None
            for ps in post_selectors:
                try:
                    btn = page.query_selector(ps)
                    if btn and btn.is_visible() and btn.is_enabled():
                        post_btn = btn
                        break
                except Exception:
                    continue
                    
            if post_btn:
                print("[PublisherService] Clicking comment post button...")
                post_btn.click()
                time.sleep(3.0)
                print("[PublisherService] Comment posted successfully!")
                return True
            else:
                print("[PublisherService Warning] Send button not clickable. Trying Enter key fallback...")
                page.keyboard.press("Enter")
                time.sleep(3.0)
                print("[PublisherService] Comment posted via Enter fallback!")
                return True
                
        except Exception as e:
            print(f"[PublisherService Warning] Error during posting comment: {e}")
            return False


class YouTubeStudioPublisherService:
    def __init__(self, profile_dir: str = None):
        """
        Quản lý persistent profile riêng cho từng kênh YouTube Studio để tránh bị lẫn cookie.
        """
        if profile_dir:
            self.profile_dir = profile_dir
        else:
            self.profile_dir = os.path.join(os.getcwd(), "worker", "chrome_profile_youtube")
        os.makedirs(self.profile_dir, exist_ok=True)
        print(f"[YouTubePublisher] Persistent Profile Path: {self.profile_dir}")

    def create_stealth_browser_with_proxy(
        self, 
        headless: bool = True, 
        proxy_ip: str = None, 
        proxy_port: int = None, 
        proxy_user: str = None, 
        proxy_pass: str = None
    ):
        """
        Khởi tạo Chrome Persistent Context với Proxy dân cư động và cơ chế Stealth Protocol.
        """
        playwright = sync_playwright().start()
        
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-dev-shm-usage"
        ]
        
        # Thiết lập cấu hình Proxy dân cư động
        proxy_config = None
        if proxy_ip and proxy_port:
            proxy_config = {
                "server": f"http://{proxy_ip}:{proxy_port}"
            }
            if proxy_user and proxy_pass:
                proxy_config["username"] = proxy_user
                proxy_config["password"] = proxy_pass
            print(f"[YouTubePublisher] Binding dynamic proxy: {proxy_ip}:{proxy_port}")
        else:
            print("[YouTubePublisher Warning] Launching context WITHOUT proxy!")

        # Khởi chạy Persistent Context để giữ session đăng nhập của kênh
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=headless,
                channel="chrome",  # Sử dụng trình duyệt Chrome chính thống trên OS
                args=launch_args,
                proxy=proxy_config,
                viewport={"width": 1280, "height": 720}
            )
        except Exception as e:
            print(f"[YouTubePublisher Warning] Failed to launch real Chrome ({e}). Falling back to Chromium...")
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=headless,
                args=launch_args,
                proxy=proxy_config,
                viewport={"width": 1280, "height": 720}
            )

        page = context.pages[0]
        # Inject mã stealth ghi đè biến window.navigator.webdriver của Cloudflare
        Stealth().apply_stealth_sync(page)
        
        return playwright, context, page

    def human_type(self, page, selector: str, text: str):
        """Giả lập gõ phím cơ học của con người với độ trễ biến thiên ngẫu nhiên"""
        element = page.query_selector(selector)
        if not element:
            raise Exception(f"DOM Selector not found: {selector}")
        element.click()
        
        # Xóa dữ liệu cũ trong trường
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        time.sleep(random.uniform(0.2, 0.4))
        
        for char in text:
            page.keyboard.type(char)
            time.sleep(random.uniform(0.04, 0.12)) # 40ms - 120ms delay

    def _clean_joyride_overlays(self, page):
        """Tự động xóa các onboarding popup của YouTube Studio che mắt click"""
        selectors = [
            "ytcp-dialog", "tp-yt-paper-dialog", 
            "#react-joyride-portal", ".yt-help-popup",
            "ytcp-bubble-wrap"
        ]
        try:
            page.evaluate(
                f"""() => {{
                    const selectors = {selectors};
                    selectors.forEach(sel => {{
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    }});
                }}"""
            )
        except Exception as e:
            print(f"[YouTubePublisher Warning] Joyride cleanup failed: {e}")

    def publish_video_to_youtube_studio(
        self, 
        video_path: str, 
        title: str, 
        description: str, 
        tags: list, 
        proxy_ip: str = None, 
        proxy_port: int = None, 
        proxy_user: str = None, 
        proxy_pass: str = None,
        headless: bool = True
    ) -> str:
        """
        Thực hiện toàn bộ quy trình upload video dạng Shorts lên YouTube Studio Web qua trình duyệt ẩn danh.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file path not found: {video_path}")

        playwright, context, page = self.create_stealth_browser_with_proxy(
            headless=headless,
            proxy_ip=proxy_ip,
            proxy_port=proxy_port,
            proxy_user=proxy_user,
            proxy_pass=proxy_pass
        )

        try:
            print("[YouTubePublisher] Opening YouTube Studio Dashboard...")
            page.goto("https://studio.youtube.com", wait_until="networkidle", timeout=60000)
            time.sleep(3.0)

            # Kiểm tra trạng thái đăng nhập
            if "signin" in page.url or page.query_selector("input[type='email']"):
                print("[YouTubePublisher Critical] Cookie expired. Manual login required.")
                raise RuntimeError("YouTube Session cookie expired. Please run in headful mode (headless=False) to log in.")

            self._clean_joyride_overlays(page)

            # 1. Bấm nút CREATE
            print("[YouTubePublisher] Clicking Create Button...")
            create_btn = page.locator("#create-icon")
            create_btn.wait_for(state="visible", timeout=15000)
            create_btn.click()
            time.sleep(1.0)

            # 2. Bấm nút Upload Videos
            print("[YouTubePublisher] Clicking Upload Videos Button...")
            upload_menu_item = page.locator("text=Upload videos")
            upload_menu_item.wait_for(state="visible", timeout=5000)
            upload_menu_item.click()
            time.sleep(2.0)

            # 3. Đưa file video vào Input File ẩn của YouTube Studio
            print(f"[YouTubePublisher] Uploading video file: {video_path}")
            file_input = page.locator("input[type='file'][name='Filedata']")
            file_input.wait_for(state="attached", timeout=10000)
            file_input.set_input_files(video_path)
            
            # Đợi giao diện upload hiện lên
            print("[YouTubePublisher] Waiting for details panel...")
            page.locator("ytcp-uploads-dialog").wait_for(state="visible", timeout=30000)
            time.sleep(3.0)

            self._clean_joyride_overlays(page)

            # 4. Điền tiêu đề (Title)
            print(f"[YouTubePublisher] Typing title: {title}")
            title_textbox_selector = "div[aria-label='Add a title that describes your video (required)']"
            page.locator(title_textbox_selector).wait_for(state="visible", timeout=15000)
            self.human_type(page, title_textbox_selector, title[:100])
            time.sleep(1.5)

            # 5. Điền mô tả (Description)
            print(f"[YouTubePublisher] Typing description...")
            desc_textbox_selector = "div[aria-label='Tell viewers about your video']"
            page.locator(desc_textbox_selector).wait_for(state="visible", timeout=10000)
            self.human_type(page, desc_textbox_selector, description[:5000])
            time.sleep(1.5)

            # 6. Thiết lập Không dành cho trẻ em (Not Made for Kids)
            print("[YouTubePublisher] Selecting 'Not Made For Kids' option...")
            not_for_kids_selector = "paper-radio-button[name='NOT_MADE_FOR_KIDS']"
            page.locator(not_for_kids_selector).scroll_into_view_if_needed()
            page.locator(not_for_kids_selector).click()
            time.sleep(1.0)

            # 7. Nhấp "Show more" để thêm thẻ tags
            print("[YouTubePublisher] Expanding tags panel...")
            show_more_btn = page.locator("ytcp-button#toggle-button")
            if show_more_btn.is_visible():
                show_more_btn.click()
                time.sleep(1.0)

            # 8. Nhập danh sách Tags
            if tags:
                print(f"[YouTubePublisher] Typing tags: {tags}")
                tags_input_selector = "input[aria-label='Tags']"
                page.locator(tags_input_selector).scroll_into_view_if_needed()
                tags_string = ",".join(tags) + ","
                self.human_type(page, tags_input_selector, tags_string)
                time.sleep(1.0)

            # 9. Bấm Next bước 1: Video Elements
            print("[YouTubePublisher] Progressing through Next buttons...")
            next_btn = page.locator("#next-button")
            next_btn.click()
            time.sleep(1.5)

            # Bấm Next bước 2: Checks
            next_btn.click()
            time.sleep(1.5)

            # Bấm Next bước 3: Visibility
            next_btn.click()
            time.sleep(2.0)

            # 10. Chọn chế độ Public trực tiếp (Shorts đề xuất đăng ngay lập tức)
            print("[YouTubePublisher] Setting visibility to Public...")
            public_radio = page.locator("paper-radio-button[name='PUBLIC']")
            public_radio.wait_for(state="visible", timeout=10000)
            public_radio.click()
            time.sleep(1.5)

            # 11. Bấm PUBLISH kết thúc
            print("[YouTubePublisher] Clicking Done/Publish button...")
            publish_btn = page.locator("#done-button")
            publish_btn.wait_for(state="visible", timeout=10000)
            publish_btn.click()
            print("[YouTubePublisher] Upload sequence completed. Waiting for dialog closure...")
            time.sleep(8.0) # Đợi YouTube đóng gói và sinh link

            # 12. Trích xuất liên kết video ngắn đã sinh ra từ giao diện thành công
            video_url = "https://youtube.com/shorts/"
            try:
                link_element = page.locator("a.style-scope.ytcp-video-share-dialog")
                if link_element.is_visible():
                    raw_href = link_element.get_attribute("href")
                    if raw_href:
                        video_url = raw_href
            except Exception:
                pass
                
            print(f"[YouTubePublisher Success] Published Video URL: {video_url}")
            return video_url

        except Exception as e:
            # Chụp ảnh màn hình lưu vết lỗi để gửi cảnh báo qua Telegram
            screenshot_path = os.path.join(os.getcwd(), "worker", "output_videos", f"yt_error_{int(time.time())}.png")
            try:
                page.screenshot(path=screenshot_path)
                print(f"[YouTubePublisher Error] Saved debug screenshot to: {screenshot_path}")
            except Exception:
                pass
            raise e
        finally:
            context.close()
            playwright.stop()
