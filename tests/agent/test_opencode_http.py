import json
from pathlib import Path

import httpx
import pytest

from evalscope.agent.external.opencode_http import OpenCodeHTTPClient, OpenCodeHTTPConfig


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

