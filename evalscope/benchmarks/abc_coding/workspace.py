"""Prepare local sources using EvalScope's environment and resource interfaces."""

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from evalscope.agent.environments.local import LocalAgentEnvironment
from evalscope.api.dataset.hub import download_dataset_file
from evalscope.constants import HubType
from evalscope.utils.asyncio_runtime import AsyncioLoopRunner

from .contracts import CaseManifest


def resource(root: Path, relative: str) -> Path:
    """Resolve case resources through the shared local dataset resolver."""
    if Path(relative).is_absolute():
        raise ValueError('Case resource paths must be relative.')
    # `data_source=HubType.LOCAL`时，`download_dataset_file`不会进行任何文件写入、复制、移动等操作，仅返回文件解析符号链接后的绝对路径
    return Path(download_dataset_file(str(root), relative, data_source=HubType.LOCAL))


def sha256(path: Path) -> str:
    """Hash a file without loading its complete contents into memory."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _hash(stream)


def _hash(stream: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    """Persist UTF-8 artifacts outside the agent workspace."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    """Run Git without a shell or interactive prompts."""
    result = subprocess.run(
        ['git', '-c', 'core.autocrlf=false', '-c', 'core.hooksPath=', *args],
        cwd=cwd,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', **(env or {})},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f'Git {args[0]} failed: {result.stderr.decode("utf-8", errors="replace")[-1500:]}')
    return result.stdout


def prepare(root: Path, manifest: CaseManifest, target: Path) -> str:
    """Copy only validated initial sources and establish a new immutable baseline."""
    if target.exists():
        raise FileExistsError(f'Workspace already exists: {target}')
    source = resource(root, manifest.development.source_directory)
    hashes = json.loads(resource(root, manifest.development.source_checksums).read_text(encoding='utf-8'))
    files = {}
    for path in source.rglob('*'):
        if path.is_symlink() or (os.name == 'nt' and path.stat().st_file_attributes & 1024):
            raise ValueError(f'Links are not allowed in initial sources: {path}')
        if '.git' in path.relative_to(source).parts:
            raise ValueError('Initial sources must not contain Git history.')
        if path.is_file():
            files[path.relative_to(source).as_posix()] = sha256(path)
    if not files or files != hashes:
        raise ValueError('Initial source inventory/checksums do not match.')
    task = resource(root, manifest.task_file)
    if sha256(task) != manifest.development.task_sha256:
        raise ValueError('Task checksum does not match.')
    environment = LocalAgentEnvironment(working_dir=str(target))
    AsyncioLoopRunner.run(environment.put_dir(source, str(target)))
    git(target, 'init')
    git(target, 'add', '-f', '--all')
    git(
        target,
        '-c',
        'user.name=EvalScope',
        '-c',
        'user.email=evalscope@localhost',
        '-c',
        'commit.gpgsign=false',
        'commit',
        '-m',
        'ABC coding initial snapshot',
    )
    return git(target, 'rev-parse', 'HEAD').decode().strip()


def archive_candidate(workspace: Path, baseline: str, artifacts: Path) -> None:
    """Capture committed and uncommitted changes, including new and binary files."""
    # A private index avoids changing the agent's staging area. Tracked files always
    # survive exclusions; ignored build outputs and common private files do not.
    index = artifacts / 'candidate.index'
    environment = {'GIT_INDEX_FILE': str(index.resolve())}
    git(workspace, 'read-tree', baseline, env=environment)
    git(workspace, 'add', '-u', env=environment)
    untracked = git(workspace, 'ls-files', '--others', '--exclude-standard', '-z', env=environment).split(b'\0')
    excluded = {'node_modules', '.venv', '__pycache__', 'dist', 'build', 'target', 'test-results', 'playwright-report'}
    for raw in untracked:
        if not raw:
            continue
        name = raw.decode('utf-8')
        path = Path(name)
        if any(part in excluded for part in path.parts) or path.name.startswith('.env'):
            continue
        if path.suffix.lower() in {'.log', '.pem', '.key'}:
            continue
        git(workspace, 'add', '--', name, env=environment)
    patch = git(workspace, 'diff', '--cached', '--binary', baseline, env=environment)
    (artifacts / 'candidate.patch').write_bytes(patch)
    tree = git(workspace, 'write-tree', env=environment).decode().strip()
    git(workspace, 'archive', '--format=zip', f'--output={artifacts / "candidate.zip"}', tree)
    with zipfile.ZipFile(artifacts / 'candidate.zip') as archive:
        if any('.git' in Path(name).parts for name in archive.namelist()):
            raise ValueError('Candidate archive unexpectedly contains Git metadata.')
    index.unlink(missing_ok=True)
    write_json(
        artifacts / 'candidate.json',
        {
            'baseline_commit': baseline,
            'candidate_tree': tree,
            'patch_sha256': sha256(artifacts / 'candidate.patch'),
            'archive_sha256': sha256(artifacts / 'candidate.zip'),
        },
    )
