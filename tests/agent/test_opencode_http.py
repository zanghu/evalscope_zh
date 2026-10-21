import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

from evalscope.agent.external.opencode_events import OpenCodeEventMonitor
from evalscope.agent.external.opencode_http import OpenCodeHTTPClient, OpenCodeHTTPConfig


class EventStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.events: queue.Queue[bytes | None] = queue.Queue()
        self.closed = threading.Event()
        self.send({'type': 'server.connected', 'properties': {}})

    def send(self, event: dict) -> None:
        self.events.put(f'data: {json.dumps(event)}\n\n'.encode())

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(.001)
                continue
            if event is None:
                return
            yield event

    async def aclose(self) -> None:
        self.closed.set()


@pytest.fixture(autouse=True)
def event_stream(monkeypatch: pytest.MonkeyPatch) -> Iterator[EventStream]:
    stream = EventStream()
    monitors = []

    def factory(client: OpenCodeHTTPClient, directory: str, session_id: str) -> OpenCodeEventMonitor:
        def handle(request: httpx.Request) -> httpx.Response:
            assert request.url.path == '/event'
            assert request.url.params['directory'] == directory
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

        monitor = OpenCodeEventMonitor(
            client.config.base_url, directory, session_id, None, client.config.event_connect_timeout,
            transport=httpx.MockTransport(handle),
        )
        monitors.append(monitor)
        return monitor

    monkeypatch.setattr(OpenCodeHTTPClient, '_event_monitor', factory)
    yield stream
    for monitor in monitors:
        monitor.close()
        assert not monitor._thread.is_alive()
    if monitors:
        assert stream.closed.is_set()


def test_http_waits_for_correlated_completion_after_initial_idle(tmp_path: Path) -> None:
    state = {'polls': 0, 'submissions': 0, 'message': ''}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == '/global/health':
            return httpx.Response(200, json={'healthy': True, 'version': 'test'})
        assert request.url.params['directory'] == str(tmp_path.resolve())
        if path == '/session':
            return httpx.Response(200, json={'id': 'ses_test', 'directory': str(tmp_path)})
        if path.endswith('prompt_async'):
            state['submissions'] += 1
            body = json.loads(request.content)
            assert body['parts'][0]['text'] == '中文需求'
            state['message'] = body['messageID']
            # Delivery happened, but the client did not receive the response.
            raise httpx.ReadTimeout('uncertain delivery')
        if path.endswith('/message'):
            state['polls'] += 1
            if state['polls'] == 1:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[
                {'info': {'role': 'user', 'id': state['message']}, 'parts': []},
                {'info': {'role': 'assistant', 'parentID': state['message'],
                          'time': {'completed': 1}, 'finish': 'stop'}, 'parts': []},
            ])
        if path == '/session/status':
            return httpx.Response(200, json={})
        if path in {'/permission', '/question'}:
            return httpx.Response(200, json=[])
        raise AssertionError(path)

    config = OpenCodeHTTPConfig(provider_id='p', model_id='m', poll_interval=.001)
    with httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handle)) as transport:
        result = OpenCodeHTTPClient(config, transport).run(tmp_path, '中文需求', 'test')
    assert result.status == 'completed'
    assert state['submissions'] == 1
    assert state['polls'] == 2


@pytest.mark.parametrize('mode,expected', [('permission', 'needs_input'), ('timeout', 'timed_out'),
                                          ('error', 'error'), ('abort_failure', 'not_stopped')])
def test_http_aborts_incomplete_attempts(tmp_path: Path, mode: str, expected: str) -> None:
    state = {'message': '', 'aborted': False}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == '/global/health':
            return httpx.Response(200, json={'healthy': True})
        if path == '/session':
            return httpx.Response(200, json={'id': 'ses_test', 'directory': str(tmp_path)})
        if path.endswith('prompt_async'):
            state['message'] = json.loads(request.content)['messageID']
            return httpx.Response(204)
        if path.endswith('/message'):
            return httpx.Response(200, json=[{'info': {'role': 'assistant', 'parentID': state['message'],
                                                       'error': {'name': 'APIError'}}, 'parts': []}]
                                  if mode == 'error' else [])
        if path.endswith('/abort'):
            state['aborted'] = True
            return httpx.Response(500 if mode == 'abort_failure' else 200, json=True)
        if path == '/session/status':
            return httpx.Response(200, json={} if state['aborted'] else {'ses_test': {'type': 'busy'}})
        if path in {'/permission', '/question'}:
            return httpx.Response(200, json=[{'sessionID': 'ses_test'}] if mode == 'permission' else [])
        raise AssertionError(path)

    config = OpenCodeHTTPConfig(provider_id='p', model_id='m', timeout=.03, poll_interval=.001)
    with httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handle)) as transport:
        result = OpenCodeHTTPClient(config, transport).run(tmp_path, 'test', 'test')
    assert state['aborted']
    assert result.status == expected


@pytest.mark.parametrize('mode,source', [
    ('session_error', 'session.error'), ('disconnect', 'event_stream'), ('malformed', 'event_stream'),
    ('idle', 'prompt_start'), ('undelivered', 'prompt_start'),
    ('busy', None), ('retry', None), ('other_session', None), ('poll_failure', 'polling'),
])
def test_http_monitors_async_failures_and_startup(
    tmp_path: Path, event_stream: EventStream, mode: str, source: str | None,
) -> None:
    state = {'message': '', 'aborted': False, 'submissions': 0}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == '/global/health':
            return httpx.Response(200, json={'healthy': True})
        if path == '/session':
            return httpx.Response(200, json={'id': 'ses_test', 'directory': str(tmp_path)})
        if path.endswith('prompt_async'):
            state['message'] = json.loads(request.content)['messageID']
            state['submissions'] += 1
            if mode in {'session_error', 'other_session'}:
                event_stream.send({
                    'type': 'session.error', 'properties': {
                        'sessionID': 'ses_other' if mode == 'other_session' else 'ses_test',
                        'error': {'name': 'UnknownError', 'data': {'message': 'Model not found: p/m'}},
                    },
                })
            if mode == 'disconnect':
                event_stream.events.put(None)
            if mode == 'malformed':
                event_stream.events.put(b'data: invalid-json\n\n')
            if mode == 'undelivered':
                raise httpx.ReadTimeout('delivery unknown')
            return httpx.Response(204)
        if path.endswith('/message'):
            if mode == 'poll_failure':
                raise httpx.ReadTimeout('status unavailable')
            return httpx.Response(200, json=[] if mode == 'undelivered' else [
                {'info': {'role': 'user', 'id': state['message']}, 'parts': []},
            ])
        if path == '/session/status':
            status = mode if mode in {'busy', 'retry'} else 'idle'
            return httpx.Response(200, json={} if state['aborted'] else {'ses_test': {'type': status}})
        if path in {'/permission', '/question'}:
            return httpx.Response(200, json=[])
        if path.endswith('/abort'):
            state['aborted'] = True
            return httpx.Response(200, json=True)
        raise AssertionError(path)

    config = OpenCodeHTTPConfig(
        provider_id='p', model_id='m', timeout=.15, prompt_start_timeout=.02 if source else .3, poll_interval=.001,
    )
    if mode in {'busy', 'retry'}:
        config.prompt_start_timeout = .02
    with httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handle)) as transport:
        result = OpenCodeHTTPClient(config, transport).run(tmp_path, 'test', 'test')
    assert state['aborted']
    assert state['submissions'] == 1
    assert result.status == ('error' if source else 'timed_out')
    assert result.diagnostics.error_source == source
    if mode == 'session_error':
        assert 'Model not found: p/m' in result.error
    if mode == 'undelivered':
        assert not result.diagnostics.prompt_accepted


@pytest.mark.parametrize('disconnect', [True, False])
def test_subscription_failure_does_not_submit(
    tmp_path: Path, event_stream: EventStream, disconnect: bool,
) -> None:
    event_stream.events.get_nowait()
    if disconnect:
        event_stream.events.put(None)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/global/health':
            return httpx.Response(200, json={'healthy': True})
        if request.url.path == '/session':
            return httpx.Response(200, json={'id': 'ses_test', 'directory': str(tmp_path)})
        if request.url.path.endswith('/abort'):
            return httpx.Response(200, json=True)
        if request.url.path == '/session/status':
            return httpx.Response(200, json={})
        raise AssertionError(f'Unexpected request: {request.url.path}')

    config = OpenCodeHTTPConfig(provider_id='p', model_id='m', event_connect_timeout=.05)
    with httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handle)) as transport:
        result = OpenCodeHTTPClient(config, transport).run(tmp_path, 'test', 'test')
    assert result.status == 'error'
    assert result.diagnostics.error_source == 'event_stream'


def test_event_parser_handles_multiline_data_and_comments(event_stream: EventStream) -> None:
    config = OpenCodeHTTPConfig(provider_id='p', model_id='m')
    client = OpenCodeHTTPClient(config)
    monitor = client._event_monitor('.', 'ses_test')
    try:
        monitor.start()
        event_stream.events.put(
            b': heartbeat\n\ndata: {"type": "session.error",\n'
            b'data: "properties": {"sessionID": "ses_test", "error": {"name": "APIError"}}}\n\n'
        )
        monitor.wait(1)
        error, failure = monitor.snapshot()
        assert 'APIError' in error
        assert failure is None
    finally:
        monitor.close()
        client.close()

