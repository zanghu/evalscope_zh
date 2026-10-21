"""Offline tests for trusted candidate replay and native scoring."""

import json
import sys
import zipfile
from pathlib import Path

import pytest

from evalscope.benchmarks.abc_coding.contracts import (
    CaseManifest,
    ExecutionResult,
    RequiredTest,
    StageResult,
    TestObservation,
    VerificationResult,
    VerificationStep,
)
from evalscope.benchmarks.abc_coding.verification import extract_candidate, grade, parse_report, run_step, verify
from evalscope.benchmarks.abc_coding.workspace import sha256, write_json


def fixture(root: Path, candidate: Path) -> tuple[CaseManifest, ExecutionResult]:
    root.mkdir()
    candidate.mkdir()
    (root / 'task.md').write_text('Implement feature', encoding='utf-8')
    write_json(root / 'source-files.json', {'main.txt': 'baseline'})
    (root / 'check.py').write_text(
        "import json\nfrom pathlib import Path\n"
        "assert Path('main.txt').read_text() == 'candidate'\n"
        "Path('unit.json').write_text(json.dumps({'testResults':[{'assertionResults':"
        "[{'fullName':'F2P-1 works','status':'passed'}]}]}))\n", encoding='utf-8')
    write_json(root / 'overlay.json', [{'package_path': 'check.py', 'target_path': 'check.py',
                                      'sha256': sha256(root / 'check.py')}])
    write_json(root / 'inventory.json', [{'id': 'F2P-1', 'suite': 'unit', 'group': 'F2P'}])
    manifest = CaseManifest(case_id='example', case_version='1', task_file='task.md', development={
        'source_directory': 'unused', 'source_checksums': 'source-files.json', 'task_sha256': sha256(root / 'task.md'),
    }, verification={
        'version': '1', 'working_directory': '.', 'overlay_manifest': 'overlay.json',
        'test_inventory': 'inventory.json', 'steps': [{'name': 'unit', 'kind': 'tests',
        'command': [sys.executable, 'check.py'], 'report_format': 'jest', 'report_path': 'unit.json'}],
    })
    write_json(root / 'case.json', manifest.model_dump())
    with zipfile.ZipFile(candidate / 'candidate.zip', 'w') as archive:
        archive.writestr('main.txt', 'candidate')
        archive.writestr('check.py', 'raise Exception("untrusted test")')
        archive.writestr('unit.json', 'stale report')
    write_json(candidate / 'candidate.json', {'archive_sha256': sha256(candidate / 'candidate.zip')})
    execution = ExecutionResult(case_id='example', case_version='1', attempt_id='original', status='completed',
                                artifact_dir=str(candidate), started_at='2026-09-18T00:00:00Z',
                                source_manifest_sha256=sha256(root / 'source-files.json'),
                                task_sha256=manifest.development.task_sha256)
    write_json(candidate / 'execution.json', execution.model_dump())
    return manifest, execution


def test_replay_overlays_trusted_files_without_touching_candidate(tmp_path: Path) -> None:
    root, candidate = tmp_path / 'case', tmp_path / 'candidate'
    manifest, execution = fixture(root, candidate)
    before = sha256(candidate / 'candidate.zip')
    result = verify(root, manifest, execution, tmp_path / 'output')
    assert result.resolved == 1
    assert result.status == 'passed'
    assert result.group_rates == {'F2P': 1}
    assert sha256(candidate / 'candidate.zip') == before
    assert (Path(result.artifact_dir) / 'verification.json').exists()


@pytest.mark.parametrize('problem', ['hash', 'version', 'tamper'])
def test_replay_rejects_bad_inputs_and_changed_trusted_files(tmp_path: Path, problem: str) -> None:
    root, candidate = tmp_path / 'case', tmp_path / 'candidate'
    manifest, execution = fixture(root, candidate)
    if problem == 'hash':
        write_json(candidate / 'candidate.json', {'archive_sha256': 'incorrect'})
    elif problem == 'version':
        execution.case_version = 'wrong'
    else:
        with (root / 'check.py').open('a', encoding='utf-8') as stream:
            stream.write("Path('check.py').write_text('modified')\n")
        write_json(root / 'overlay.json', [{'package_path': 'check.py', 'target_path': 'check.py',
                                          'sha256': sha256(root / 'check.py')}])
    result = verify(root, manifest, execution, tmp_path / 'output')
    assert result.status == 'needs_review'
    assert result.resolved is None


def test_zip_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / 'candidate.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('../outside.txt', 'bad')
    with pytest.raises(ValueError, match='Unsafe'):
        extract_candidate(archive, tmp_path / 'workspace')
    assert not (tmp_path / 'outside.txt').exists()


@pytest.mark.parametrize('status,exit_code,expected', [('failed', 1, 0), ('passed', 0, 1),
                                                     ('skipped', 0, None), ('failed', 0, None)])
def test_grading_distinguishes_failure_from_missing_evidence(status: str, exit_code: int, expected: int | None) -> None:
    result = VerificationResult(verification_id='v', case_id='c', case_version='1', development_attempt_id='a',
                                artifact_dir='unused', stages=[StageResult(name='unit', exit_code=exit_code, log_path='x')],
                                tests=[TestObservation(suite='unit', title='F2P-1 test', status=status)])
    inventory = [RequiredTest(id='F2P-1', suite='unit', group='F2P')]
    grade(result, inventory)
    assert result.resolved == expected
    result.resolved = None
    result.tests *= 2
    grade(result, inventory)
    assert result.resolved is None


def test_junit_and_timeout(tmp_path: Path) -> None:
    xml = tmp_path / 'report.xml'
    xml.write_text('<testsuites><testsuite><testcase name="P2P-1"><failure>bad</failure></testcase>'
                   '<testcase name="F2P-1"><skipped/></testcase></testsuite></testsuites>', encoding='utf-8')
    results = parse_report(xml, 'junit', 'e2e')
    assert [item.status for item in results] == ['failed', 'skipped']
    result = run_step(VerificationStep(name='slow', kind='gate', command=[sys.executable, '-c',
                      'import time; time.sleep(60)'], timeout=.2), tmp_path, {}, tmp_path)
    assert result.timed_out


@pytest.mark.parametrize('corrupt', [False, True])
def test_native_verification_only_pipeline(tmp_path: Path, corrupt: bool) -> None:
    from evalscope import TaskConfig, run_task

    dataset = tmp_path / 'dataset'
    dataset.mkdir()
    fixture(dataset / 'case', tmp_path / 'candidate')
    if corrupt:
        write_json(tmp_path / 'candidate/candidate.json', {'archive_sha256': 'mismatch'})
    (dataset / 'default_test.jsonl').write_text(json.dumps({'case_id': 'example', 'case_manifest': 'case/case.json'}) + '\n')
    run_task(TaskConfig(model='replay-only', eval_type='mock_llm', datasets=['abc_coding'],
                        eval_batch_size=1, work_dir=str(tmp_path / 'outputs'), no_timestamp=True,
                        dataset_args={'abc_coding': {'local_path': str(dataset), 'extra_params': {
                            'coding': {'mode': 'verify_only', 'candidates': {'example': str(tmp_path / 'candidate')}}}}}))
    summary = json.loads((tmp_path / 'outputs/artifacts/abc_coding/batch-verification.json').read_text())
    assert summary['resolved_rate'] == (None if corrupt else 1)
    assert summary['coverage'] == (0 if corrupt else 1)
    assert list((tmp_path / 'outputs/reports').rglob('abc_coding.json'))


def test_opencode_trace_links_tools_to_review_messages() -> None:
    from evalscope.benchmarks.abc_coding.trajectory import session_messages, session_trace

    session = {'messages': [
        {'info': {'id': 'u', 'role': 'user'}, 'parts': [{'type': 'text', 'text': 'task'}]},
        {'info': {'id': 'a', 'role': 'assistant', 'time': {'created': 1000, 'completed': 2000}, 'finish': 'stop'},
         'parts': [{'type': 'text', 'text': 'done'}, {'type': 'tool', 'id': 't', 'callID': 'c', 'tool': 'bash',
                   'state': {'status': 'completed', 'input': {'command': 'test'}, 'output': 'ok',
                             'time': {'start': 1100, 'end': 1900}}}]},
    ]}
    execution = ExecutionResult(case_id='c', attempt_id='a', artifact_dir='unused', started_at='now')
    messages = session_messages(session)
    trace = session_trace(session, execution)
    assert [m.role for m in messages] == ['user', 'assistant', 'tool']
    assert messages[-1].tool_call_id == messages[1].tool_calls[0].id
    tool_result = next(e for e in trace.events if e.type.value == 'tool_result')
    assert tool_result.message_id == messages[-1].id
    assert tool_result.payload['id'] == 'c'
    assert trace.events[-1].type.value == 'submit'
