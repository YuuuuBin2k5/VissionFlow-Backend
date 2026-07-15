import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from worker.config import (
    SCHEDULE_TIMEZONE, POSTING_SCHEDULE_PRESET, POSTING_SCHEDULE_PRESETS,
    MIN_HOURS_BETWEEN_POSTS,
)


def _parse_slot(slot: str):
    hour_str, minute_str = slot.split(":", 1)
    return int(hour_str), int(minute_str)

def get_daily_posting_slots():
    return POSTING_SCHEDULE_PRESETS.get(
        POSTING_SCHEDULE_PRESET,
        POSTING_SCHEDULE_PRESETS["office_student"],
    )

def get_schedule_timezone():
    try:
        return ZoneInfo(SCHEDULE_TIMEZONE)
    except ZoneInfoNotFoundError:
        if SCHEDULE_TIMEZONE == "Asia/Bangkok":
            return datetime.timezone(datetime.timedelta(hours=7), name="Asia/Bangkok")
        raise

def build_safe_campaign_schedule(total_videos: int, start_from=None):
    """
    Build a two-posts-per-day schedule with a hard minimum gap.
    Naive datetimes are returned because the current MySQL schema stores DATETIME.
    """
    timezone = get_schedule_timezone()
    now = start_from or datetime.datetime.now(timezone)
    first_day = now.date() + datetime.timedelta(days=1)
    slots = get_daily_posting_slots()
    min_gap = datetime.timedelta(hours=MIN_HOURS_BETWEEN_POSTS)

    schedule = []
    last_time = None
    for idx in range(total_videos):
        slot = slots[idx % len(slots)]
        day_offset = idx // len(slots)
        hour, minute = _parse_slot(slot)
        scheduled_time = datetime.datetime.combine(
            first_day + datetime.timedelta(days=day_offset),
            datetime.time(hour=hour, minute=minute),
            tzinfo=timezone,
        )

        if last_time and scheduled_time < last_time + min_gap:
            scheduled_time = last_time + min_gap

        schedule.append(scheduled_time.replace(tzinfo=None))
        last_time = scheduled_time

    return schedule
