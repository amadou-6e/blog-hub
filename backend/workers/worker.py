"""Independent leased worker for BlogHub's durable job queue."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from backend.store.backends.sqlite import SQLiteStore
from backend.store.job_queue import JobLeaseLost, UncertainSideEffect

logger = logging.getLogger(__name__)


class JobCanceled(RuntimeError):
    pass


class JobTimedOut(RuntimeError):
    pass


class RetryableJobError(RuntimeError):
    pass


class PermanentJobError(RuntimeError):
    pass


JobHandler = Callable[["JobContext", dict[str, Any]], dict[str, Any] | None]


class JobContext:
    def __init__(
        self, store: SQLiteStore, job: dict, worker_id: str,
        *, lease_seconds: int, stopped: threading.Event,
        canceled: threading.Event, timed_out: threading.Event,
    ) -> None:
        self.store = store
        self.job = job
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self._stopped = stopped
        self._canceled = canceled
        self._timed_out = timed_out
        self._deadline = time.monotonic() + max(1, int(job["timeout_seconds"]))

    @property
    def job_id(self) -> str:
        return self.job["job_id"]

    @property
    def user_id(self) -> str:
        return self.job["user_id"]

    def check_stopped(self) -> None:
        try:
            if self.store.is_job_cancel_requested(self.job_id, self.worker_id):
                self._canceled.set()
        except JobLeaseLost:
            self._stopped.set()
        if time.monotonic() >= self._deadline:
            self._timed_out.set()
        if self._stopped.is_set():
            raise JobLeaseLost(f"Lease lost for {self.job_id}")
        if self._canceled.is_set():
            raise JobCanceled(f"Job {self.job_id} was canceled")
        if self._timed_out.is_set():
            raise JobTimedOut(f"Job {self.job_id} exceeded its timeout")

    def checkpoint(self, **state: Any) -> dict:
        self.check_stopped()
        return self.store.checkpoint_job(self.job_id, self.worker_id, state)

    def run_effect(
        self, effect_key: str, operation: Callable[[], Any], *,
        release_on_error: bool = False,
    ) -> Any:
        self.check_stopped()
        cached, acquired = self.store.begin_job_effect(
            self.job_id, self.worker_id, effect_key
        )
        if not acquired:
            return cached
        try:
            result = operation()
        except Exception:
            if release_on_error:
                self.store.abort_job_effect(self.job_id, self.worker_id, effect_key)
            raise
        self.check_stopped()
        self.store.complete_job_effect(
            self.job_id, self.worker_id, effect_key, result
        )
        return result


class DurableWorker:
    def __init__(
        self, store: SQLiteStore, handlers: dict[str, JobHandler], *,
        worker_id: str | None = None,
        queues: tuple[str, ...] = ("default", "agents", "publishing"),
        lease_seconds: int = 30, poll_seconds: float = 1.0,
    ) -> None:
        self.store = store
        self.handlers = handlers
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:12]}"
        self.queues = queues
        self.lease_seconds = max(3, lease_seconds)
        self.poll_seconds = max(0.05, poll_seconds)
        self._shutdown = threading.Event()

    def _monitor_job(
        self, job: dict, finished: threading.Event, lease_lost: threading.Event,
        canceled: threading.Event, timed_out: threading.Event,
    ) -> None:
        interval = max(0.5, self.lease_seconds / 3)
        started = time.monotonic()
        monitor_store = self.store
        close_monitor = False
        if self.store._db_path != ":memory:":
            monitor_store = SQLiteStore(self.store._db_path, str(self.store._blobs_dir))
            close_monitor = True
        try:
            while not finished.wait(interval):
                try:
                    if monitor_store.is_job_cancel_requested(job["job_id"], self.worker_id):
                        canceled.set()
                    if time.monotonic() - started >= job["timeout_seconds"]:
                        timed_out.set()
                    if not monitor_store.heartbeat_job(
                        job["job_id"], self.worker_id, lease_seconds=self.lease_seconds
                    ):
                        lease_lost.set()
                        return
                except JobLeaseLost:
                    lease_lost.set()
                    return
        finally:
            if close_monitor:
                monitor_store.close()

    def _mark_session_terminal(self, job: dict, status: str, error: str) -> None:
        session_id = job.get("payload", {}).get("session_id")
        if not session_id:
            return
        session_status = "canceled" if status == "canceled" else "failed"
        try:
            self.store.update_agent_session_status(
                job["user_id"], session_id, session_status, error
            )
        except (KeyError, ValueError):
            logger.exception("Could not update agent session for terminal job %s", job["job_id"])

    def run_once(self) -> bool:
        job = self.store.claim_job(
            self.worker_id, queues=self.queues, lease_seconds=self.lease_seconds
        )
        if job is None:
            return False
        handler = self.handlers.get(job["type"])
        if handler is None:
            status = self.store.fail_job(
                job["job_id"], self.worker_id,
                f"No handler registered for job type {job['type']}", retryable=False,
            )
            self._mark_session_terminal(job, status, "No worker handler registered")
            return True

        finished = threading.Event()
        lease_lost = threading.Event()
        canceled = threading.Event()
        timed_out = threading.Event()
        monitor = threading.Thread(
            target=self._monitor_job,
            args=(job, finished, lease_lost, canceled, timed_out),
            name=f"{self.worker_id}-heartbeat", daemon=True,
        )
        monitor.start()
        context = JobContext(
            self.store, job, self.worker_id, lease_seconds=self.lease_seconds,
            stopped=lease_lost, canceled=canceled, timed_out=timed_out,
        )
        try:
            result = handler(context, job["payload"]) or {}
            context.check_stopped()
            self.store.complete_job(
                job["user_id"], job["job_id"], result=result, worker_id=self.worker_id
            )
        except JobCanceled as exc:
            status = self.store.fail_job(
                job["job_id"], self.worker_id, str(exc), retryable=False
            )
            self._mark_session_terminal(job, status, str(exc))
        except JobTimedOut as exc:
            status = self.store.fail_job(job["job_id"], self.worker_id, str(exc))
            if status in {"failed", "canceled"}:
                self._mark_session_terminal(job, status, str(exc))
        except UncertainSideEffect as exc:
            self.store.defer_job(job["job_id"], self.worker_id, str(exc))
        except JobLeaseLost:
            logger.warning("Worker %s lost lease for job %s", self.worker_id, job["job_id"])
        except PermanentJobError as exc:
            status = self.store.fail_job(
                job["job_id"], self.worker_id, str(exc), retryable=False
            )
            self._mark_session_terminal(job, status, str(exc))
        except Exception as exc:
            logger.exception("Job %s attempt failed", job["job_id"])
            status = self.store.fail_job(job["job_id"], self.worker_id, str(exc))
            if status in {"failed", "canceled"}:
                self._mark_session_terminal(job, status, str(exc))
        finally:
            finished.set()
            monitor.join(timeout=max(1.0, self.lease_seconds))
        return True

    def run_forever(self) -> None:
        logger.info("Worker %s listening on queues %s", self.worker_id, self.queues)
        while not self._shutdown.is_set():
            if not self.run_once():
                self._shutdown.wait(self.poll_seconds)

    def stop(self) -> None:
        self._shutdown.set()
