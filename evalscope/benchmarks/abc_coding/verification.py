"""Minimal local verifier: trusted overlay, declared commands, and test evidence."""

import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import time
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from pydantic import TypeAdapter

from .contracts import (
    CaseManifest,
    ExecutionResult,
    OverlayFile,
    RequiredTest,
    StageResult,
    TestObservation,
    VerificationResult,
    VerificationStep,
)
from .workspace import resource, sha256, write_json


def destination(root: Path, relative: str) -> Path:
    """Resolve a portable path without allowing drive paths, ADS, or traversal."""
    normalized = relative.replace('\\', '/')
    path = PurePosixPath(normalized)
    if path.is_absolute() or ':' in normalized or '..' in path.parts:
        raise ValueError(f'Unsafe relative path: {relative}')
    result = (root / normalized).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes workspace: {relative}')
    return result


# 以下函数提供的额外功能：
# 1. 拒绝符号链接：stat.S_ISLNK(entry.external_attr >> 16) 检查文件属性，如果 zip 条目是符号链接就抛出异常。因为 git archive 生成的 zip 可能包含符号链接，直接解压可能被恶意利用来覆盖任意文件。
# 2. 拒绝路径穿越：通过 path.relative_to(target) 检查解压路径是否仍在目标目录内，防止 ../ 或绝对路径逃逸出目标目录。
# 3. 拒绝重复路径：seen 集合记录已处理的路径（不区分大小写），防止 zip 中有多个条目指向同一位置导致覆盖冲突。
# 4. 拒绝 .git 目录：防止解压出的内容包含 .git 元数据，避免智能体利用 git 历史作弊。
def extract_candidate(archive: Path, target: Path) -> None:
    """Extract a complete candidate once, rejecting links and ambiguous paths."""
    target.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            path = destination(target, entry.filename)
            key = str(path).casefold()
            if key in seen or stat.S_ISLNK(entry.external_attr >> 16) or '.git' in path.relative_to(target).parts:
                raise ValueError(f'Unsupported archive entry: {entry.filename}')
            seen.add(key)
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as incoming, path.open('wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)


def parse_report(path: Path, format_name: str, suite: str) -> list[TestObservation]:
    """Read Jest JSON or JUnit XML without inferring success from console text."""
    results = []
    if format_name == 'jest':
        report = json.loads(path.read_text(encoding='utf-8-sig'))
        for test_file in report['testResults']:
            assertions = test_file.get('assertionResults', [])
            if test_file.get('status') == 'failed' and not assertions:
                results.append(TestObservation(suite=suite, title=test_file.get('name', ''), status='error'))
            for assertion in assertions:
                status = assertion['status']
                results.append(
                    TestObservation(
                        suite=suite,
                        title=assertion.get('fullName', assertion.get('title', '')),
                        status=status if status in {'passed', 'failed'} else 'skipped',
                        detail='\n'.join(assertion.get('failureMessages', []))[:4000],
                    )
                )
    elif format_name == 'junit':
        document = ElementTree.parse(path)
        for test in document.iter('testcase'):
            failure = test.find('failure')
            error = test.find('error')
            status = 'error' if error is not None else 'failed' if failure is not None else 'passed'
            if test.find('skipped') is not None:
                status = 'skipped'
            results.append(
                TestObservation(
                    suite=suite,
                    title=test.get('name', ''),
                    status=status,
                    detail=(
                        (failure.text or '') if failure is not None else (error.text or '') if error is not None else ''
                    )[:4000],
                )
            )
    else:
        raise ValueError(f'Unsupported report format: {format_name}')
    return results


def run_step(step: VerificationStep, cwd: Path, environment: dict[str, str], logs: Path) -> StageResult:
    """Run a declared command with file-backed output and bounded process lifetime."""
    command = list(step.command)
    executable = shutil.which(command[0])
    if not executable:
        raise FileNotFoundError(f'Command not installed: {command[0]}')
    # npm's Windows shim is replaced by its native Node entry point, without a shell.
    if os.name == 'nt' and Path(executable).suffix.lower() in {'.cmd', '.ps1'}:
        npm = Path(executable).parent / 'node_modules/npm/bin/npm-cli.js'
        if Path(executable).stem != 'npm' or not npm.is_file():
            raise ValueError('Use an executable and argument array instead of a Windows shell shim.')
        command = [shutil.which('node') or 'node', str(npm), *command[1:]]
    else:
        command[0] = executable
    log = logs / f'{step.name}.log'
    result = StageResult(name=step.name, log_path=str(log))
    started = time.monotonic()
    with log.open('wb') as stream:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env={**os.environ, **environment},
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt',
        )
        try:
            result.exit_code = process.wait(timeout=step.timeout)
        except subprocess.TimeoutExpired:
            result.timed_out = True
        finally:
            if process.poll() is None:
                result.timed_out = True
                if os.name == 'nt':
                    subprocess.run(
                        ['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15, check=True
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
    result.duration_seconds = time.monotonic() - started
    return result


def grade(result: VerificationResult, inventory: list[RequiredTest]) -> None:
    """Grade complete evidence; unknown or contradictory evidence stays unscored."""
    required = [test for test in inventory if test.required]
    if not required or len({test.id for test in required}) != len(required):
        raise ValueError('Required test inventory must be nonempty and contain unique IDs.')
    matched: dict[str, TestObservation] = {}
    for test in required:
        observations = [
            item
            for item in result.tests
            if item.suite == test.suite and re.search(r'(?<![\w-])' + re.escape(test.id) + r'(?![\w-])', item.title)
        ]
        if len(observations) != 1 or observations[0].status not in {'passed', 'failed'}:
            result.reason = f'Required test missing, duplicated, skipped, or errored: {test.id}'
            return
        matched[test.id] = observations[0]
    if any(t.status in {'error', 'skipped'} for t in result.tests):
        result.reason = 'Test execution errors or skipped tests require review.'
        return
    for stage in result.stages:
        observed = [t for t in result.tests if t.suite == stage.name]
        if stage.timed_out or (stage.exit_code != 0 and not any(t.status == 'failed' for t in observed)):
            result.reason = f'Command failed without complete assertion evidence: {stage.name}'
            return
        if stage.exit_code == 0 and any(t.status == 'failed' for t in observed):
            result.reason = f'Exit code contradicts test report: {stage.name}'
            return
    groups = Counter(t.group for t in required)
    result.group_rates = {
        group: sum(matched[t.id].status == 'passed' for t in required if t.group == group) / count
        for group, count in groups.items()
    }
    result.resolved = int(all(t.status == 'passed' for t in result.tests))
    result.status = 'passed' if result.resolved else 'failed'
    result.reason = (
        'All required tests and gates passed.' if result.resolved else 'Test assertions failed; inspect evidence.'
    )


def verify(
    root: Path, manifest: CaseManifest, execution: ExecutionResult, output: Path, *, baseline: bool = False
) -> VerificationResult:
    """Verify an existing immutable candidate without invoking a coding agent."""
    started = time.monotonic()
    folder = output / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=False)
    logs = folder / 'logs'
    logs.mkdir()
    result = VerificationResult(
        verification_id=folder.name,
        case_id=manifest.case_id,
        case_version=manifest.case_version,
        development_attempt_id=execution.attempt_id,
        artifact_dir=str(folder),
        baseline=baseline,
    )
    protected: dict[Path, str] = {}
    try:
        config = manifest.verification
        if config is None:
            raise ValueError('Case has no verification recipe.')
        result.recipe_version = config.version
        if execution.case_id != manifest.case_id or execution.case_version != manifest.case_version:
            raise ValueError('Candidate and case versions differ.')
        if execution.source_manifest_sha256 != sha256(resource(root, manifest.development.source_checksums)):
            raise ValueError('Candidate source identity differs from current case.')
        if execution.task_sha256 != manifest.development.task_sha256:
            raise ValueError('Candidate task identity differs from current case.')
        if execution.status != 'completed':
            if execution.status == 'timed_out':
                result.status, result.resolved = 'budget_exceeded', 0
            result.reason = f'Development status: {execution.status}; {execution.error or ""}'
            return result
        artifacts = Path(execution.artifact_dir)
        archive = artifacts / 'candidate.zip'
        info = json.loads((artifacts / 'candidate.json').read_text(encoding='utf-8'))
        result.candidate_sha256 = sha256(archive)
        if result.candidate_sha256 != info['archive_sha256']:
            raise ValueError('Candidate archive checksum mismatch.')
        overlay_path = resource(root, config.overlay_manifest)
        inventory_path = resource(root, config.test_inventory)
        overlay = TypeAdapter(list[OverlayFile]).validate_json(overlay_path.read_bytes())
        inventory = TypeAdapter(list[RequiredTest]).validate_json(inventory_path.read_bytes())
        if not overlay or len({f.target_path.casefold() for f in overlay}) != len(overlay):
            raise ValueError('Overlay must be nonempty with unique target paths.')
        if len({s.name for s in config.steps}) != len(config.steps):
            raise ValueError('Verification stage names must be unique.')
        test_stages = {s.name for s in config.steps if s.kind == 'tests'}
        if {t.suite for t in inventory if t.required} != test_stages:
            raise ValueError('Test inventory and test stages differ.')
        import hashlib

        result.verifier_sha256 = hashlib.sha256(
            config.model_dump_json().encode() + overlay_path.read_bytes() + inventory_path.read_bytes()
        ).hexdigest()
        write_json(folder / 'recipe.json', config.model_dump())
        shutil.copyfile(overlay_path, folder / 'overlay-manifest.json')
        shutil.copyfile(inventory_path, folder / 'test-inventory.json')
        workspace = folder / 'workspace'
        extract_candidate(archive, workspace)
        for item in overlay:
            source = resource(root, item.package_path)
            if sha256(source) != item.sha256:
                raise ValueError(f'Trusted file checksum mismatch: {item.package_path}')
            target = destination(workspace, item.target_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            protected[target] = item.sha256
        cwd = destination(workspace, config.working_directory)
        for port in config.ports:
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                except OSError:
                    result.status, result.reason = 'infrastructure_error', f'Port already in use: {port}'
                    return result
        for step in config.steps:
            report = destination(cwd, step.report_path) if step.report_path else None
            if step.kind == 'tests' and (report is None or step.report_format is None):
                raise ValueError(f'Test stage requires a report: {step.name}')
            if report:
                report.parent.mkdir(parents=True, exist_ok=True)
                report.unlink(missing_ok=True)
            stage = run_step(step, cwd, config.environment, logs)
            result.stages.append(stage)
            stage.report_path = str(report) if report else None
            if step.kind == 'setup' and stage.exit_code != 0:
                result.reason = f'Dependency setup failed; inspect {stage.log_path}'
                return result
            if report:
                try:
                    result.tests.extend(parse_report(report, step.report_format, step.name))
                except (OSError, ValueError, KeyError, ElementTree.ParseError) as exc:
                    result.tests.append(
                        TestObservation(
                            suite=step.name,
                            title='Report unavailable',
                            status='error',
                            detail=str(exc)[:4000],
                        )
                    )
        grade(result, inventory)
    except FileNotFoundError as exc:
        result.reason = str(exc)
        # Missing reports are not automatically infrastructure failures.
        if 'Command not installed:' in str(exc):
            result.status = 'infrastructure_error'
    except (OSError, ValueError, KeyError, ElementTree.ParseError, zipfile.BadZipFile) as exc:
        result.reason = f'{type(exc).__name__}: {exc}'
    finally:
        changed = [str(path) for path, expected in protected.items() if not path.is_file() or sha256(path) != expected]
        if changed:
            result.status, result.resolved, result.group_rates = 'needs_review', None, {}
            result.reason = 'Trusted files changed during verification: ' + ', '.join(changed)
        result.duration_seconds = time.monotonic() - started
        write_json(folder / 'verification.json', result.model_dump())
    return result
