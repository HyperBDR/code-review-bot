"""In-memory review queue for single-instance deployments."""

import logging
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ReviewTask:
    """A queued review task with lifecycle callbacks."""

    project_id: int
    commit_sha: str
    run_review: Callable[[], str]
    on_start: Callable[[], None]
    on_success: Callable[[str], None]
    on_timeout: Callable[[], None]
    on_error: Callable[[Exception], None]
    on_superseded: Callable[[], None] | None = None
    dedupe_key: str = ""
    review_type: str = "review"
    mr_iid: int | None = None
    _superseded: bool = False

    @property
    def superseded(self) -> bool:
        """Return whether this queued task has been replaced by a newer task."""
        return self._superseded

    def mark_superseded(self) -> None:
        """Mark this pending task as replaced by a newer task."""
        self._superseded = True

    def report_superseded(self) -> None:
        """Invoke the optional superseded callback."""
        if self.on_superseded is not None:
            self.on_superseded()

    def run(self) -> None:
        """Run the review and invoke callbacks for status reporting."""
        if self.superseded:
            logger.info("[%s queue] task skipped: superseded", self.review_type)
            self.report_superseded()
            return

        logger.info("[%s queue] task starting", self.review_type)
        try:
            self.on_start()
            result = self.run_review()
            self.on_success(result)
            logger.info("[%s queue] task completed", self.review_type)
        except subprocess.TimeoutExpired:
            self.on_timeout()
            logger.warning("%s review timeout", self.review_type)
        except Exception as exc:
            logger.exception("%s review task error", self.review_type)
            self.on_error(exc)


class ReviewQueue:
    """Global FIFO worker pool with per-project concurrency limits."""

    def __init__(
        self,
        max_pending: int = 100,
        *,
        worker_count: int = 3,
        project_concurrency: int = 2,
        start_workers: bool = True,
    ) -> None:
        self.max_pending = max(1, max_pending)
        self.worker_count = max(1, worker_count)
        self.project_concurrency = max(1, project_concurrency)
        self._start_workers = start_workers
        self._condition = threading.Condition()
        self._queue: deque[ReviewTask] = deque()
        self._workers: list[threading.Thread] = []
        self._pending_count = 0
        self._active_count = 0
        self._active_by_project: dict[int, int] = {}

        if self._start_workers:
            self._ensure_workers()

    @property
    def pending_count(self) -> int:
        """Return queued-but-not-running task count."""
        with self._condition:
            return self._pending_count

    @property
    def active_count(self) -> int:
        """Return currently running task count."""
        with self._condition:
            return self._active_count

    @property
    def active_project_ids(self) -> set[int]:
        """Return project IDs with active review tasks."""
        with self._condition:
            return set(self._active_by_project)

    def set_limits(
        self,
        *,
        max_pending: int,
        worker_count: int,
        project_concurrency: int,
    ) -> None:
        """Update queue limits and start extra workers if needed."""
        with self._condition:
            self.max_pending = max(1, max_pending)
            self.worker_count = max(1, worker_count)
            self.project_concurrency = max(1, project_concurrency)
            if self._start_workers:
                self._ensure_workers_locked()
            self._condition.notify_all()

    def try_enqueue(
        self,
        task: ReviewTask,
        *,
        on_accepted: Callable[[], None] | None = None,
    ) -> bool:
        """Append a task if capacity allows; return False when full."""
        superseded_tasks: list[ReviewTask] = []
        with self._condition:
            supersede_candidates: list[ReviewTask] = []
            if task.dedupe_key:
                for pending in self._queue:
                    if (
                        pending.dedupe_key == task.dedupe_key
                        and not pending.superseded
                    ):
                        supersede_candidates.append(pending)

            projected_pending = self._pending_count - len(supersede_candidates)
            if projected_pending >= self.max_pending:
                logger.warning(
                    "[queue] full pending=%s max=%s project_id=%s",
                    self._pending_count,
                    self.max_pending,
                    task.project_id,
                )
                return False

            for pending in supersede_candidates:
                pending.mark_superseded()
                superseded_tasks.append(pending)
                self._pending_count -= 1

            self._queue.append(task)
            self._pending_count += 1
            if self._start_workers:
                self._ensure_workers_locked()
            self._condition.notify_all()

        if on_accepted is not None:
            on_accepted()

        for pending in superseded_tasks:
            try:
                pending.report_superseded()
            except Exception:
                logger.exception("failed to report superseded review task")

        return True

    def drain_all(self) -> None:
        """Synchronously drain all runnable tasks; intended for tests."""
        while True:
            task = self._pop_next_ready()
            if task is None:
                return
            try:
                task.run()
            finally:
                self._finish_task(task.project_id)

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        """Wait until all queues are empty and no tasks are running."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._condition:
                idle = self._pending_count == 0 and self._active_count == 0
            if idle:
                return True
            time.sleep(0.01)
        return False

    def _ensure_workers(self) -> None:
        with self._condition:
            self._ensure_workers_locked()

    def _ensure_workers_locked(self) -> None:
        while len(self._workers) < self.worker_count:
            index = len(self._workers) + 1
            thread = threading.Thread(
                target=self._worker,
                daemon=True,
                name=f"review-worker-{index}",
            )
            self._workers.append(thread)
            thread.start()

    def _worker(self) -> None:
        logger.info("[queue] worker started")
        while True:
            task = self._wait_for_next_ready()
            try:
                task.run()
            finally:
                self._finish_task(task.project_id)

    def _wait_for_next_ready(self) -> ReviewTask:
        with self._condition:
            while True:
                task = self._pop_next_ready_locked()
                if task is not None:
                    return task
                self._condition.wait()

    def _pop_next_ready(self) -> ReviewTask | None:
        with self._condition:
            return self._pop_next_ready_locked()

    def _pop_next_ready_locked(self) -> ReviewTask | None:
        for task in list(self._queue):
            if task.superseded:
                self._queue.remove(task)
                continue

            active_for_project = self._active_by_project.get(task.project_id, 0)
            if active_for_project >= self.project_concurrency:
                continue

            self._queue.remove(task)
            self._pending_count -= 1
            self._active_count += 1
            self._active_by_project[task.project_id] = active_for_project + 1
            return task

        return None

    def _finish_task(self, project_id: int) -> None:
        with self._condition:
            self._active_count -= 1
            active_for_project = self._active_by_project.get(project_id, 0) - 1
            if active_for_project > 0:
                self._active_by_project[project_id] = active_for_project
            else:
                self._active_by_project.pop(project_id, None)
            self._condition.notify_all()


_queue_lock = threading.Lock()
_review_queue: ReviewQueue | None = None


def get_review_queue(
    max_pending: int = 100,
    *,
    worker_count: int = 3,
    project_concurrency: int = 2,
) -> ReviewQueue:
    """Return the process-global review queue."""
    global _review_queue
    with _queue_lock:
        if _review_queue is None:
            _review_queue = ReviewQueue(
                max_pending=max_pending,
                worker_count=worker_count,
                project_concurrency=project_concurrency,
            )
        else:
            _review_queue.set_limits(
                max_pending=max_pending,
                worker_count=worker_count,
                project_concurrency=project_concurrency,
            )
        return _review_queue


def reset_review_queue() -> None:
    """Reset the process-global queue; intended for tests."""
    global _review_queue
    with _queue_lock:
        _review_queue = None
