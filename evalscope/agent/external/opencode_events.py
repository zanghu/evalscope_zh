"""Cancellable SSE monitoring for a single OpenCode session."""

import asyncio
import json
import threading
from typing import Any

import httpx


class OpenCodeEventMonitor:
    """Receive session errors without blocking the synchronous evaluation loop."""

    def __init__(
        self,
        base_url: str,
        directory: str,
        session_id: str,
        auth: tuple[str, str] | None,
        connect_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_args = dict(base_url=base_url, auth=auth, trust_env=False, transport=transport)
        self._directory = directory
        self._session_id = session_id
        self._connect_timeout = connect_timeout
        self._ready = threading.Event()
        self._closing = threading.Event()
        self._changed = threading.Event()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._error: str | None = None
        self._failure: str | None = None
        self._thread = threading.Thread(target=self._run, name='opencode-events', daemon=True)

    def start(self) -> None:
        """Wait for server.connected before allowing prompt submission."""
        self._thread.start()
        if not self._ready.wait(self._connect_timeout):
            with self._lock:
                self._failure = 'OpenCode event subscription did not become ready.'
            raise RuntimeError(self._failure)
        _, failure = self.snapshot()
        if failure:
            raise RuntimeError(failure)

    def snapshot(self) -> tuple[str | None, str | None]:
        """Return the first session error and any monitoring failure."""
        with self._lock:
            return self._error, self._failure

    def wait(self, timeout: float) -> None:
        """Wake the polling loop when an error or connection failure arrives."""
        self._changed.wait(timeout)

    def close(self) -> None:
        """Cancel network reads and join the receiver before returning."""
        self._closing.set()
        with self._lock:
            loop, task = self._loop, self._task
            if loop is not None and task is not None:
                loop.call_soon_threadsafe(task.cancel)
        if self._thread.ident is not None:
            self._thread.join()

    def _run(self) -> None:
        asyncio.run(self._receive())

    async def _receive(self) -> None:
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
        try:
            if self._closing.is_set():
                return
            timeout = httpx.Timeout(self._connect_timeout, read=30)
            async with httpx.AsyncClient(**self._client_args, timeout=timeout) as client:
                async with client.stream('GET', '/event', params={'directory': self._directory}) as response:
                    response.raise_for_status()
                    if 'text/event-stream' not in response.headers.get('content-type', ''):
                        raise ValueError('Expected an OpenCode SSE response.')
                    data: list[str] = []
                    async for line in response.aiter_lines():
                        if not line:
                            if data:
                                self._handle(json.loads('\n'.join(data)))
                                data.clear()
                        elif line.startswith('data:'):
                            data.append(line[5:].removeprefix(' '))
                    raise RuntimeError('OpenCode event stream closed unexpectedly.')
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            with self._lock:
                self._failure = f'OpenCode event monitoring failed: {type(exc).__name__}: {str(exc)[:2000]}'
            self._ready.set()
            self._changed.set()
        finally:
            with self._lock:
                self._loop = None
                self._task = None

    def _handle(self, event: dict[str, Any]) -> None:
        if event.get('type') == 'server.connected':
            self._ready.set()
        properties = event.get('properties', {})
        if event.get('type') == 'session.error' and properties.get('sessionID') == self._session_id:
            with self._lock:
                if self._error is None:
                    self._error = json.dumps(properties.get('error'), ensure_ascii=False)[:4000]
            self._changed.set()
