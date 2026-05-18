"""Background scheduler worker for daily jobs."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from licitaciones_mcp.config import Settings
from licitaciones_mcp.jobs.runner import DailyJobRunner
from licitaciones_mcp.observability import get_logger
from licitaciones_mcp.storage.database import TenderDatabase
from licitaciones_mcp.storage.models import DailyJobRecord, SchedulerHeartbeatRecord, new_id

_log = get_logger(__name__)


def _trigger_for(record: DailyJobRecord) -> CronTrigger:
    if record.cron:
        return CronTrigger.from_crontab(record.cron, timezone="UTC")
    return CronTrigger(hour=record.hour_utc, minute=0, timezone="UTC")


class TenderScheduler:
    """Reload daily-job definitions from the DB and run them with APScheduler."""

    def __init__(
        self,
        settings: Settings,
        database: TenderDatabase,
        *,
        reload_interval_seconds: int = 60,
    ) -> None:
        self.settings = settings
        self.database = database
        self.runner = DailyJobRunner(database, settings)
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.reload_interval_seconds = reload_interval_seconds
        self.worker_id = f"{socket.gethostname()}:{new_id()[:8]}"
        self._stopping = asyncio.Event()
        self._known_signatures: dict[str, tuple[str | None, int, bool]] = {}

    async def _run_job(self, job_id: str) -> None:
        try:
            job = await self.database.get_daily_job(job_id)
            if job is None:
                _log.warning("scheduled_job_missing", job_id=job_id)
                return
            await self.runner.run_job(job, refresh_sources=True)
        except Exception as exc:  # noqa: BLE001
            _log.warning("scheduled_job_failed", job_id=job_id, error=str(exc))

    async def _load_jobs(self) -> int:
        async with self.database.session_factory() as session:
            records = (await session.execute(select(DailyJobRecord))).scalars().all()
        active: dict[str, tuple[str | None, int, bool]] = {}
        for record in records:
            if not record.enabled:
                continue
            sig = (record.cron, record.hour_utc, record.enabled)
            active[record.id] = sig
            if self._known_signatures.get(record.id) == sig:
                continue
            if self.scheduler.get_job(record.id) is not None:
                self.scheduler.remove_job(record.id)
            self.scheduler.add_job(
                self._run_job,
                trigger=_trigger_for(record),
                id=record.id,
                args=[record.id],
                replace_existing=True,
            )
        # Remove jobs that disappeared or got disabled.
        for job_id in list(self._known_signatures):
            if job_id not in active and self.scheduler.get_job(job_id) is not None:
                self.scheduler.remove_job(job_id)
        self._known_signatures = active
        return len(active)

    async def _heartbeat(self, jobs_loaded: int, note: str | None = None) -> None:
        async with self.database.session_factory() as session:
            session.add(
                SchedulerHeartbeatRecord(
                    worker_id=self.worker_id,
                    beat_at=datetime.now(UTC),
                    jobs_loaded=jobs_loaded,
                    note=note,
                )
            )
            await session.commit()

    async def run_forever(self) -> None:
        """Start the scheduler loop until cancelled or stop() is called."""

        self.scheduler.start()
        _log.info("scheduler_started", worker_id=self.worker_id)
        try:
            while not self._stopping.is_set():
                try:
                    jobs_loaded = await self._load_jobs()
                    await self._heartbeat(jobs_loaded)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("scheduler_reload_failed", error=str(exc))
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.reload_interval_seconds
                    )
                except TimeoutError:
                    continue
        finally:
            self.scheduler.shutdown(wait=False)
            _log.info("scheduler_stopped", worker_id=self.worker_id)

    def stop(self) -> None:
        self._stopping.set()
