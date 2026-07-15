import platform
from typing import Dict, List, Optional

from worker.config import BROWSER_CHANNEL, BROWSER_EXECUTABLE_PATH, BROWSER_EXTRA_ARGS


def browser_architecture() -> str:
    return platform.machine().lower()


def is_arm64_host() -> bool:
    return browser_architecture() in {"aarch64", "arm64"}


def base_browser_args(headless: bool = True) -> List[str]:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]
    if not headless:
        args.append("--start-maximized")
    args.extend(BROWSER_EXTRA_ARGS)
    return args


def browser_launch_options(headless: bool = True, persistent: bool = False) -> Dict[str, object]:
    options: Dict[str, object] = {
        "headless": headless,
        "args": base_browser_args(headless=headless),
    }

    if BROWSER_EXECUTABLE_PATH:
        options["executable_path"] = BROWSER_EXECUTABLE_PATH
        return options

    # Chrome channel is useful on Windows/x86 desktops, but it is fragile on
    # ARM64 Linux. Default Playwright Chromium is the safest deploy baseline.
    if BROWSER_CHANNEL and not is_arm64_host():
        options["channel"] = BROWSER_CHANNEL
    elif BROWSER_CHANNEL and is_arm64_host():
        print(
            "[BrowserRuntime Warning] BROWSER_CHANNEL is ignored on ARM64. "
            "Set BROWSER_EXECUTABLE_PATH to a system Chromium binary if needed."
        )

    return options


def describe_browser_runtime() -> str:
    if BROWSER_EXECUTABLE_PATH:
        source = f"executable_path={BROWSER_EXECUTABLE_PATH}"
    elif BROWSER_CHANNEL and not is_arm64_host():
        source = f"channel={BROWSER_CHANNEL}"
    else:
        source = "playwright-chromium"
    return f"{source}, arch={browser_architecture()}"
