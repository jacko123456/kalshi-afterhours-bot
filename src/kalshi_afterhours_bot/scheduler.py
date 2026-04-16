from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import SessionPhase


@dataclass(slots=True)
class ScheduleWindow:
    timezone: str
    capture_reference_time: str
    begin_repricing_time: str
    end_overnight_time: str
    reprice_every_minutes: int

    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(hour=int(hours), minute=int(minutes))


def current_phase(now: datetime, schedule: ScheduleWindow) -> SessionPhase:
    """Map wall-clock time to the bot's high-level session phase."""
    local_now = now.astimezone(schedule.tzinfo())
    capture_t = _parse_hhmm(schedule.capture_reference_time)
    begin_t = _parse_hhmm(schedule.begin_repricing_time)
    overnight_end_t = _parse_hhmm(schedule.end_overnight_time)

    if local_now.time() < capture_t:
        if local_now.time() >= overnight_end_t:
            return SessionPhase.DAYTIME_FLATTEN
        return SessionPhase.PRE_CAPTURE

    if capture_t <= local_now.time() < begin_t:
        return SessionPhase.CAPTURE_WINDOW

    if local_now.time() >= begin_t or local_now.time() < overnight_end_t:
        return SessionPhase.OVERNIGHT_REPRICE

    return SessionPhase.DAYTIME_FLATTEN


def next_reprice_time(now: datetime, schedule: ScheduleWindow) -> datetime:
    """Return the next wall-clock anchored repricing time.

    Why wall-clock anchoring:
    It prevents overnight drift. If you want every five minutes from 4:05 PM,
    this keeps the cycle aligned to 4:05, 4:10, 4:15, and so on.
    """
    local_now = now.astimezone(schedule.tzinfo())
    begin_t = _parse_hhmm(schedule.begin_repricing_time)
    begin_dt = local_now.replace(hour=begin_t.hour, minute=begin_t.minute, second=0, microsecond=0)
    if local_now < begin_dt:
        return begin_dt

    delta_minutes = int((local_now - begin_dt).total_seconds() // 60)
    step = schedule.reprice_every_minutes
    next_multiple = ((delta_minutes // step) + 1) * step
    return begin_dt + timedelta(minutes=next_multiple)
