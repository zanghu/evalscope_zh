import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from evalscope.agent.external.opencode_http import OpenCodeHTTPConfig, OpenCodeOutcome
from evalscope.benchmarks.abc_coding.abc_coding_adapter import ABCCodingAdapter
from evalscope.benchmarks.abc_coding.contracts import CaseManifest
from evalscope.benchmarks.abc_coding.workspace import archive_candidate, git, prepare, resource, sha256, write_json
from evalscope.constants import ScoreStatus


def case(root: Path) -> CaseManifest:
    (root / 'initial').mkdir(parents=True)
    (root / 'initial/main.txt').write_text('initial', encoding='utf-8')
    (root / 'initial/deleted.txt').write_text('delete me', encoding='utf-8')
    (root / 'task.md').write_text('修改功能', encoding='utf-8')
    (root / 'verifier').mkdir()
    (root / 'verifier/secret.txt').write_text('hidden', encoding='utf-8')
    write_json(root / 'checksums.json', {p.name: sha256(p) for p in (root / 'initial').iterdir()})
    manifest = CaseManifest(case_id=root.name, case_version='1', task_file='task.md', development={
        'source_directory': 'initial', 'source_checksums': 'checksums.json', 'task_sha256': sha256(root / 'task.md'),
    })
    write_json(root / 'case.json', manifest.model_dump())
    return manifest


def test_workspace_and_committed_new_binary_changes(tmp_path: Path) -> None:
    root = tmp_path / 'case'
    manifest = case(root)
    workspace = tmp_path / 'workspace'
    baseline = prepare(root, manifest, workspace)
    assert not (workspace / 'verifier').exists()
    (workspace / 'main.txt').write_text('changed', encoding='utf-8')
    (workspace / 'committed-new.txt').write_text('new in agent commit', encoding='utf-8')
    git(workspace, 'add', '--all')
    git(workspace, '-c', 'user.name=test', '-c', 'user.email=test@localhost', '-c', 'commit.gpgsign=false',
        'commit', '-m', 'agent commit')
    (workspace / 'new.bin').write_bytes(b'\x00\xff\x00')
    (workspace / 'deleted.txt').unlink()
    (workspace / 'node_modules').mkdir()
    (workspace / 'node_modules/cache.txt').write_text('excluded', encoding='utf-8')
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    archive_candidate(workspace, baseline, artifacts)
    with zipfile.ZipFile(artifacts / 'candidate.zip') as archive:
        assert archive.read('new.bin') == b'\x00\xff\x00'
        assert archive.read('main.txt') == b'changed'
        assert archive.read('committed-new.txt') == b'new in agent commit'
        assert 'deleted.txt' not in archive.namelist()
        assert 'node_modules/cache.txt' not in archive.namelist()
    replay = tmp_path / 'replay'
    prepare(root, manifest, replay)
    git(replay, 'apply', str(artifacts / 'candidate.patch'))
    assert (replay / 'new.bin').read_bytes() == b'\x00\xff\x00'
    assert not (replay / 'deleted.txt').exists()
    with pytest.raises(FileExistsError):
        prepare(root, manifest, workspace)


def test_checksums_and_resource_boundaries(tmp_path: Path) -> None:
    root = tmp_path / 'case'
    manifest = case(root)
    with pytest.raises(ValueError):
        resource(root, '../outside')
    (root / 'initial/main.txt').write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError, match='checksums'):
        prepare(root, manifest, tmp_path / 'workspace')


def test_batch_cli_pipeline_records_failure_then_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import evalscope.benchmarks.abc_coding.abc_coding_adapter as module
    from evalscope import TaskConfig, run_task

    dataset = tmp_path / 'dataset'
    case(dataset / 'bad')
    case(dataset / 'good')
    (dataset / 'bad/initial/main.txt').write_text('tampered', encoding='utf-8')
    (dataset / 'default_test.jsonl').write_text('\n'.join(json.dumps({
        'case_id': name, 'case_manifest': f'{name}/case.json'}) for name in ['bad', 'good']) + '\n', encoding='utf-8')

    class Service:
        def __init__(self, *args: object) -> None:
            pass

        def __enter__(self) -> 'Service':
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def close(self) -> None:
            pass

        def run(self, directory: Path, instruction: str, title: str) -> OpenCodeOutcome:
            assert instruction == '修改功能'
            assert not (directory / 'verifier').exists()
            (directory / 'new.txt').write_text('done', encoding='utf-8')
            return OpenCodeOutcome(status='completed', session_id='ses_test')

    monkeypatch.setattr(module, 'OpenCodeService', Service)
    run_task(TaskConfig(model='unused-opencode-http', eval_type='mock_llm', datasets=['abc_coding'],
                        eval_batch_size=1, work_dir=str(tmp_path / 'outputs'), no_timestamp=True,
                        dataset_args={'abc_coding': {'local_path': str(dataset), 'extra_params': {
                            'opencode': {'provider_id': 'p', 'model_id': 'm'}}}}))
    results = list((tmp_path / 'outputs').rglob('execution.json'))
    assert len(results) == 2
    statuses = {json.loads(p.read_text(encoding='utf-8'))['status'] for p in results}
    assert statuses == {'completed', 'error'}
    score = ABCCodingAdapter.match_score(None, '', '', '', SimpleNamespace(metadata={}))
    assert score.status == ScoreStatus.EXCLUDED
    assert score.value == {}
