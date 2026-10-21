"""Direct HTTP control of an OpenCode server (no model bridge or CLI prompts)."""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class OpenCodeHTTPConfig(BaseModel):
    """Server connection and per-attempt execution policy."""

    model_config = ConfigDict(extra='forbid')
    base_url: str = 'http://127.0.0.1:4096'
    start_server: bool = False
    executable: str = 'opencode'
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    agent: str = 'build'
    timeout: float = Field(default=1800, gt=0)
    request_timeout: float = Field(default=15, gt=0)
    poll_interval: float = Field(default=1, gt=0)
    startup_timeout: float = Field(default=30, gt=0)
    session_timeout: float = Field(default=120, gt=0)
    abort_timeout: float = Field(default=15, gt=0)
    password_env: str = 'OPENCODE_SERVER_PASSWORD'
    username: str = 'opencode'
    permissions: list[dict[str, str]] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_server(self) -> 'OpenCodeHTTPConfig':
        parsed = urlparse(self.base_url)
        if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('ABC coding requires a local HTTP server.')
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
            raise ValueError('Use a plain server URL; credentials must come from the configured environment variable.')
        for rule in self.permissions:
            if set(rule) != {'permission', 'pattern', 'action'} or rule['action'] not in {'allow', 'deny', 'ask'}:
                raise ValueError('Permissions require permission, pattern and action (allow/deny/ask).')
        return self


class OpenCodeOutcome(BaseModel):
    """A stopped session's execution outcome, not a correctness verdict."""

    status: Literal['completed', 'error', 'timed_out', 'needs_input', 'not_stopped']
    session_id: str
    server_version: str = ''
    messages: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class OpenCodeHTTPClient:
    """Submit once, reconcile uncertain delivery, and wait for a terminal reply."""

    def __init__(self, config: OpenCodeHTTPConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        password = os.environ.get(config.password_env)
        self.client = client or httpx.Client(
            base_url=config.base_url,
            timeout=config.request_timeout,
            trust_env=False,
            auth=(config.username, password) if password else None,
        )

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self.client.close()

    def request(self, method: str, path: str, directory: str | None = None, **kwargs: Any) -> Any:
        """Issue a UTF-8 JSON request; never replay a mutating request automatically."""
        response = self.client.request(method, path, params={'directory': directory} if directory else None, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def health(self) -> dict[str, Any]:
        """Require a healthy OpenCode endpoint and return its version."""
        result = self.request('GET', '/global/health')
        if result.get('healthy') is not True:
            raise RuntimeError('OpenCode health check failed.')
        return result

    def _abort(self, session_id: str, directory: str) -> bool:
        try:
            self.request('POST', f'/session/{session_id}/abort', directory)
            deadline = time.monotonic() + self.config.abort_timeout
            while time.monotonic() < deadline:
                states = self.request('GET', '/session/status', directory)
                if states.get(session_id, {}).get('type', 'idle') == 'idle':
                    return True
                time.sleep(self.config.poll_interval)
        except (httpx.HTTPError, ValueError):
            return False
        return False

    def run(self, directory: Path, instruction: str, title: str) -> OpenCodeOutcome:
        """Run one fresh session and distinguish idle, blocked, failed and completed states."""
        directory_text = str(directory.resolve())
        health = self.health()
        body: dict[str, Any] = {'title': title}
        if self.config.permissions:
            body['permission'] = self.config.permissions
        # 1. 创建会话
        session = self.request('POST', '/session', directory_text, json=body, timeout=self.config.session_timeout)
        session_id = session['id']
        result = OpenCodeOutcome(status='error', session_id=session_id, server_version=health.get('version', ''))
        # An explicit message ID allows reconciliation after an HTTP timeout.
        message_id = f'msg_{uuid.uuid4().hex}'
        prompt = {
            'messageID': message_id,
            'agent': self.config.agent,
            'model': {'providerID': self.config.provider_id, 'modelID': self.config.model_id},
            'parts': [{'type': 'text', 'text': instruction}],
        }
        deadline = time.monotonic() + self.config.timeout
        try:
            actual_directory = Path(session.get('directory', directory_text)).resolve()
            if actual_directory != directory.resolve():
                raise ValueError('OpenCode session directory does not match the requested workspace.')
            try:
                # 2. 下达任务
                self.request('POST', f'/session/{session_id}/prompt_async', directory_text, json=prompt)
            except httpx.TransportError:
                # Delivery is unknown. Poll by message ID instead of sending twice.
                pass
            while time.monotonic() < deadline:
                try:
                    messages = self.request('GET', f'/session/{session_id}/message', directory_text)
                    result.messages = messages
                    states = self.request('GET', '/session/status', directory_text)
                    for endpoint in ('/permission', '/question'):
                        pending = self.request('GET', endpoint, directory_text)
                        if any(item.get('sessionID') == session_id for item in pending):
                            result.status = 'needs_input'
                            result.error = f'Pending {endpoint[1:]} request; no automatic approval.'
                            return self._stop(result, directory_text)
                    accepted = any(m['info'].get('id') == message_id for m in messages)
                    replies = [
                        m
                        for m in messages
                        if m['info'].get('role') == 'assistant' and m['info'].get('parentID') == message_id
                    ]
                    if replies:
                        latest = replies[-1]
                        info = latest['info']
                        if info.get('error'):
                            result.error = str(info['error'])
                            return self._stop(result, directory_text)
                        pending_tools = any(
                            p.get('type') == 'tool' and p.get('state', {}).get('status') in {'pending', 'running'}
                            for m in replies
                            for p in m.get('parts', [])
                        )
                        finished = info.get('time', {}).get('completed') and info.get('finish') not in {
                            None,
                            'tool-calls',
                            'unknown',
                        }
                        idle = states.get(session_id, {}).get('type', 'idle') == 'idle'
                        if accepted and finished and idle and not pending_tools:
                            result.status = 'completed'
                            return result
                except httpx.TransportError:
                    pass
                time.sleep(self.config.poll_interval)
            result.status = 'timed_out'
            result.error = 'Agent budget exhausted (or prompt delivery could not be confirmed).'
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            result.error = f'{type(exc).__name__}: {exc}'
        return self._stop(result, directory_text)

    def _stop(self, result: OpenCodeOutcome, directory: str) -> OpenCodeOutcome:
        if not self._abort(result.session_id, directory):
            result.status = 'not_stopped'
            result.error = f'{result.error or "Execution failed"}; cancellation could not be confirmed.'
        return result


class OpenCodeService:
    """Own only explicitly requested background servers; never stop an attached service."""

    def __init__(self, config: OpenCodeHTTPConfig, log_dir: Path) -> None: # config 对应于`abc-coding-prd-full.json`配置文件中的`data_args.abc_coding.exstra_params.opencode`对应的字段
        self.config = config
        self.log_dir = log_dir
        self.process: subprocess.Popen | None = None
        self.log: Any = None

    # 这里没有使用`@contextmanager`装饰器，而是使用老式方法：通过实现`__enter__`和`__exit__`来支持`with...as`调用
    def __enter__(self) -> OpenCodeHTTPClient:
        client = OpenCodeHTTPClient(self.config)
        if not self.config.start_server:
            try:
                client.health()
                return client
            except Exception:
                client.close()
                raise
        try:
            try:
                client.health()
            except httpx.ConnectError:
                pass
            else:
                raise RuntimeError('Server already exists; use start_server=false to attach explicitly.')
            executable = shutil.which(self.config.executable) # C:\nvm4w\nodejs\opencode.CMD
            if not executable:
                raise FileNotFoundError(f'OpenCode executable not found: {self.config.executable}')
            # .cmd 后缀名类似于 .bat 脚本，.ps1 后缀名是 powershell 脚本
            if os.name == 'nt' and Path(executable).suffix.lower() in {'.cmd', '.ps1'}:
                # C:\nvm4w\nodejs\node_modules\opencode-ai\bin\opencode.exe
                native = Path(executable).parent / 'node_modules/opencode-ai/bin/opencode.exe'
                if not native.is_file():
                    raise ValueError('Set executable to the native opencode.exe path.')
                executable = str(native)
            parsed = urlparse(self.config.base_url)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.log = (self.log_dir / 'opencode-server.log').open('wb')
            # 注释1：
            # `stdin=subprocess.DEVNULL`的效果
            # - 子进程的标准输入被重定向到空设备，即子进程无法从标准输入读取到任何实际数据。
            # - 立即遇到 EOF：子进程尝试从 stdin 读取数据时，会立即收到文件结束符（EOF），就像用户直接按了 Ctrl+D（Unix）或 Ctrl+Z（Windows）一样。
            # - 输入为空：子进程读取到的输入是空的，不会阻塞等待用户输入。避免挂起：防止子进程因为等待输入而卡住，导致整个程序无法继续执行。
            # 注释2：
            # 命令：C:\nvm4w\nodejs\node_modules\opencode-ai\bin\opencode.exe serve --hostname 127.0.0.1 --port 41960
            self.process = subprocess.Popen(
                [executable, 'serve', '--hostname', parsed.hostname, '--port', str(parsed.port or 80)],
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                # creationflags 是 windows 专用参数，它接受一个或多个标志位（通过按位或 | 组合），这些标志位直接传递给 Windows 的 CreateProcess API。
                # 在 Unix/Linux 系统上，该参数会被忽略（传入 0 即可）。
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, # 子进程无窗口启动
            )
            deadline = time.monotonic() + self.config.startup_timeout
            while time.monotonic() < deadline:
                # `process.poll()`对子进程进行非阻塞检查：立即返回子进程的退出状态，不会等待子进程结束。返回值含义：
                # - 如果子进程仍在运行，返回 None。
                # - 如果子进程已经退出，返回退出码（整数，如 0 表示正常退出，非零表示异常）。
                if self.process.poll() is not None:
                    raise RuntimeError('OpenCode server exited; inspect opencode-server.log.')
                try:
                    client.health()
                    return client
                except httpx.ConnectError:
                    time.sleep(0.2)
            raise TimeoutError('OpenCode server startup timed out.')
        except Exception:
            client.close()
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args: Any) -> None:
        if self.process is not None and self.process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'], capture_output=True, timeout=15)
            else:
                self.process.terminate()
            self.process.wait(timeout=15)
        if self.log:
            self.log.close()
