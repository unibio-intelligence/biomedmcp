"""Bounded study workers; cancelled waiters cannot create unlimited background work."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from .errors import ResearchError


class StudyWorkers:
    def __init__(self, *, workers=2, max_pending=4, thread_name="ubi-study", busy_message=None):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=thread_name)
        self.busy_message = busy_message or "Study workers are busy; retry later."
        self.max_pending = max_pending
        self.pending = 0
        self.lock = threading.Lock()

    async def run(self, function, *args, **kwargs):
        with self.lock:
            if self.pending >= self.max_pending:
                raise ResearchError("provider_busy", self.busy_message, retryable=True)
            self.pending += 1
        try:
            future = self.executor.submit(function, *args, **kwargs)
        except BaseException:
            with self.lock:
                self.pending -= 1
            raise

        def release(done):
            with self.lock:
                self.pending -= 1

        future.add_done_callback(release)
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            # Queued work can be cancelled; running work keeps its permit until
            # it actually finishes, even after its asynchronous caller leaves.
            future.cancel()
            raise

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


study_workers = StudyWorkers()
