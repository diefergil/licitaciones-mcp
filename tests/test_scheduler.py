"""Scheduler trigger tests."""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from licitaciones_mcp.jobs.scheduler import _trigger_for
from licitaciones_mcp.storage.models import DailyJobRecord


def _cron_field_value(trigger: CronTrigger, name: str) -> str:
    return next(str(field) for field in trigger.fields if field.name == name)


def test_trigger_for_hourly_daily_job() -> None:
    record = DailyJobRecord(
        name="daily",
        filters={},
        hour_utc=8,
        cron=None,
        enabled=True,
    )

    trigger = _trigger_for(record)

    assert _cron_field_value(trigger, "hour") == "8"
    assert _cron_field_value(trigger, "minute") == "0"


def test_trigger_for_cron_job() -> None:
    record = DailyJobRecord(
        name="cron",
        filters={},
        hour_utc=8,
        cron="15 6 * * 1-5",
        enabled=True,
    )

    trigger = str(_trigger_for(record))
    assert "day_of_week='1-5'" in trigger
    assert "hour='6'" in trigger
    assert "minute='15'" in trigger
