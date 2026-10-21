"""Local coding case orchestration through the existing EvalScope pipeline."""

import json
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from evalscope.agent.external.opencode_http import OpenCodeHTTPConfig, OpenCodeService
from evalscope.api.benchmark import BenchmarkMeta
from evalscope.api.benchmark.adapters import AgentAdapter
from evalscope.api.dataset import DatasetDict, MemoryDataset, Sample
from evalscope.api.evaluator import InferenceResult, TaskState
from evalscope.api.messages import ChatMessageUser
from evalscope.api.metric import Score
from evalscope.api.metric.semantics import MetricSelector
from evalscope.api.model import Model, ModelOutput
from evalscope.api.registry import register_benchmark
from evalscope.constants import ScoreStatus, Tags
from evalscope.utils import get_logger
from evalscope.utils.import_utils import is_build_doc

from .contracts import CaseManifest, CaseRecord, CodingRunConfig, ExecutionResult
from .trajectory import session_messages, session_trace
from .verification import verify
from .workspace import archive_candidate, prepare, resource, sha256, write_json


@register_benchmark(
    # BenchmarkMeta 是一个 dataclass
    # BenchmarkMeta 中的字段会在`evalscope.api.registry.py`文件中的`get_bechmark`函数中调用`metadata._update(config.dataset_args.get(name, {}))`更新
    # 更新的主要效果之一是此处定义的`extra_params`的值被配置文件`abc-coding-prd-full.json`中的`data_args.abc_coding.extra_params`替换。
    BenchmarkMeta(
        name='abc_coding',
        pretty_name='ABC Coding',
        dataset_id='abc_coding',
        evaluation_version='v1.1', # 属于 protected_fields
        tags=[Tags.CODING, Tags.AGENT, Tags.CUSTOM],
        eval_split='test',
        prompt_template='{question}',
        metric_list=['resolved', 'f2p_pass_rate', 'p2p_pass_rate', 'evaluation_coverage'],
        primary_metric=MetricSelector(name='resolved', aggregation='mean'),
        few_shot_mode='disabled', # 属于 protected_fields
        description="""
## Overview
ABC Coding runs local repository development tasks through an OpenCode HTTP server. It consumes a local JSONL case index
and preserves candidate code and session records. Optional local verification grades trusted repository tests.

## Task Description
- **Task Type**: Repository-level software development
- **Input**: A task document and a checksummed initial source directory
- **Output**: Candidate source archive, binary Git patch, session transcript, and execution metadata
- **Domain**: Custom software engineering cases

## Key Features
- Uses the standard local dataset loader for selection, limits, and repeats.
- Creates a fresh local Git baseline per attempt without exposing verifier files or solution history.
- Uses HTTP session control rather than CLI prompt input or output parsing.
- Preserves failures per case and supports serial batches with multiple repositories.
- Supports verification-only replay and baseline calibration without calling a coding model.

## Evaluation Notes
- Requires Git, a configured OpenCode server, and the project's local toolchain.
- OpenCode calls its configured provider directly; EvalScope's model bridge is not involved.
- Use eval_type=mock_llm as an unused framework model placeholder and eval_batch_size=1.
- Development-only runs exclude functional scores. Verification reports resolved, group pass rates, and evaluation coverage.
- Verification uses fresh candidate copies, trusted overlays, declared commands, and Jest JSON or JUnit XML reports.
- Incomplete evidence is unscored; failed assertions score zero. Local execution is not adversarial isolation.
- Local execution is not a security sandbox. Pending permission/question requests stop the attempt for review.
""",
        # 根据`evalscope.api.benchmark.meta.py`文件中`BenchmarkMeta._update_extra_params`方法的实现，
        # 后续在`evalscope.api.registry.py`的`get_benchmark`函数中之心`metadata._update`更新`BenchmarkMeta`对象的属性值时，
        # 用于更新的配置文件中的`extra_params`中的 key 必须是在初始化的`extra_params`中出现过的，否则会抛出异常
        extra_params={
            'opencode': {'type': 'dict', 'value': {}, 'description': 'OpenCodeHTTPConfig connection and policy.'},
            'coding': {'type': 'dict', 'value': {}, 'description': 'CodingRunConfig mode and candidate directories.'},
        },
    )
)
class ABCCodingAdapter(AgentAdapter):
    """Bridge standard local samples to isolated per-attempt coding workspaces."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.connection: OpenCodeHTTPConfig | None = None
        self._attempts: list[dict[str, Any]] = []
        self.coding = CodingRunConfig()
        self._verifications: list[dict[str, Any]] = []

    def load(self) -> tuple[DatasetDict, None]:
        if is_build_doc():
            return DatasetDict({'default': MemoryDataset([], name='default')}), None
        if self._task_config.eval_batch_size != 1:
            raise ValueError('abc_coding currently requires eval_batch_size=1.')
        if self._task_config.eval_type != 'mock_llm' or self._task_config.agent_config is not None:
            raise ValueError('Use eval_type=mock_llm and omit agent_config; opencode config selects the real model.')
        if self._task_config.use_cache:
            raise ValueError('ABC coding cache resume is not yet supported; use a new run.')
        if self._task_config.ignore_errors:
            raise ValueError('Keep ignore_errors=false so unconfirmed cancellation stops the batch.')
        # 注意1：`self.extra_params`在`evalscope.api.registry.py`的`get_benchmark`中被`metadata._update`更新过
        # 注意2：`self.extra_params`并不会返回`self._benchmark_meta.extra_params`的原始数据，对于`extra_params`中满足"BenchmarkMeta._is_spec_entry"的字段，仅返回其"value"字段的值
        print(f'@@@ In ABCCodingAdapter.load, self.extra_params = {self.extra_params}')
        self.coding = CodingRunConfig.model_validate(self.extra_params.get('coding', {}))
        if self.coding.mode in {'develop', 'develop_and_verify'}:
            self.connection = OpenCodeHTTPConfig.model_validate(self.extra_params.get('opencode', {}))
        return self.load_from_disk(use_local_loader=True)

    def record_to_sample(self, record: dict[str, Any]) -> Sample:
        entry = CaseRecord.model_validate(record)
        return Sample(input=f'ABC coding case: {entry.case_id}', target='', metadata=entry.model_dump())

    def _case(self, entry: CaseRecord) -> tuple[Path, CaseManifest]:
        dataset = Path(self.dataset_id).resolve()
        root = dataset if dataset.is_dir() else dataset.parent
        path = resource(root, entry.case_manifest)
        manifest = CaseManifest.model_validate_json(path.read_text(encoding='utf-8'))
        if manifest.case_id != entry.case_id:
            raise ValueError('Index and manifest case IDs differ.')
        return path.parent, manifest

    def _replay(self, model: Model, sample: Sample) -> InferenceResult:
        entry = CaseRecord.model_validate(sample.metadata)
        root, manifest = self._case(entry)
        artifacts = Path(self.output_dir).resolve() / 'artifacts' / 'abc_coding' / entry.case_id / uuid.uuid4().hex
        artifacts.mkdir(parents=True, exist_ok=False)
        if self.coding.mode == 'verify_baseline':
            archive = resource(root, manifest.source_archive)
            shutil.copyfile(archive, artifacts / 'candidate.zip')
            write_json(artifacts / 'candidate.json', {'archive_sha256': sha256(archive)})
            result = ExecutionResult(
                case_id=entry.case_id,
                case_version=manifest.case_version,
                attempt_id=artifacts.name,
                status='completed',
                started_at=datetime.now(timezone.utc).isoformat(),
                artifact_dir=str(artifacts),
                source_manifest_sha256=sha256(resource(root, manifest.development.source_checksums)),
                task_sha256=manifest.development.task_sha256,
            )
            session = {}
        else:
            try:
                source = Path(self.coding.candidates[entry.case_id]).resolve()
                result = ExecutionResult.model_validate_json((source / 'execution.json').read_bytes())
                result.artifact_dir = str(source)
                session = (
                    json.loads((source / 'session.json').read_text(encoding='utf-8'))
                    if (source / 'session.json').exists()
                    else {}
                )
            except (OSError, ValueError, KeyError) as exc:
                result = ExecutionResult(
                    case_id=entry.case_id,
                    case_version=manifest.case_version,
                    attempt_id=artifacts.name,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    artifact_dir=str(artifacts),
                    error=f'Candidate replay unavailable: {exc}',
                    source_manifest_sha256=sha256(resource(root, manifest.development.source_checksums)),
                    task_sha256=manifest.development.task_sha256,
                )
                session = {}
        write_json(artifacts / 'execution.json', result.model_dump())
        write_json(artifacts / 'session.json', session)
        sample.metadata.update(execution=result.model_dump(), verification_output=str(artifacts))
        sample.input = [ChatMessageUser(content=resource(root, manifest.task_file).read_text(encoding='utf-8'))]
        return InferenceResult(
            output=ModelOutput.from_content(model.name, result.model_dump_json()),
            trace=session_trace(session, result),
            messages=session_messages(session),
        )

    def _on_inference(self, model: Model, sample: Sample) -> ModelOutput | InferenceResult:
        if self.coding.mode in {'verify_only', 'verify_baseline'}:
            return self._replay(model, sample)
        started = time.monotonic()
        attempt = uuid.uuid4().hex
        entry = CaseRecord.model_validate(sample.metadata)
        artifacts = Path(self.output_dir).resolve() / 'artifacts' / 'abc_coding' / entry.case_id / attempt
        artifacts.mkdir(parents=True, exist_ok=False)
        result = ExecutionResult(
            case_id=entry.case_id,
            attempt_id=attempt,
            artifact_dir=str(artifacts),
            started_at=datetime.now(timezone.utc).isoformat(),
            provider_id=self.connection.provider_id,
            model_id=self.connection.model_id,
        )
        workspace = artifacts / 'workspace'
        result.workspace = str(workspace)
        try:
            dataset = Path(self.dataset_id).resolve()
            root = dataset if dataset.is_dir() else dataset.parent
            manifest_path = resource(root, entry.case_manifest)
            manifest = CaseManifest.model_validate_json(manifest_path.read_text(encoding='utf-8'))
            if manifest.case_id != entry.case_id:
                raise ValueError('Index and manifest case IDs differ.')
            result.case_version = manifest.case_version
            result.source_manifest_sha256 = sha256(
                resource(manifest_path.parent, manifest.development.source_checksums)
            )
            result.task_sha256 = manifest.development.task_sha256
            result.baseline_commit = prepare(manifest_path.parent, manifest, workspace)
            directory = resource(workspace, manifest.development.working_directory)
            instruction = resource(manifest_path.parent, manifest.task_file).read_text(encoding='utf-8')
            sample.input = [ChatMessageUser(content=instruction)]
            write_json(artifacts / 'run-config.json', self.connection.model_dump())
            with OpenCodeService(self.connection, artifacts) as client:
                try:
                    outcome = client.run(directory, instruction, f'{entry.case_id}/{attempt}')
                finally:
                    client.close()
            result.status = outcome.status
            result.session_id = outcome.session_id
            result.server_version = outcome.server_version
            result.error = outcome.error
            write_json(artifacts / 'session.json', outcome.model_dump())
            if outcome.status != 'not_stopped':
                archive_candidate(workspace, result.baseline_commit, artifacts)
        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError, httpx.HTTPError) as exc:
            result.status = 'error'
            result.error = f'{type(exc).__name__}: {exc}'
        result.duration_seconds = time.monotonic() - started
        write_json(artifacts / 'execution.json', result.model_dump())
        sample.metadata['execution'] = result.model_dump()
        self._attempts.append(result.model_dump())
        summary = Path(self.output_dir) / 'artifacts' / 'abc_coding' / 'batch-execution.json'
        write_json(summary, {'functional_evaluation': 'not_run', 'attempts': self._attempts})
        # Cancellation failure makes another case unsafe to start on this server.
        # Preserve all evidence and fail the batch instead of pretending isolation.
        if result.status == 'not_stopped':
            raise RuntimeError(
                'OpenCode cancellation could not be confirmed; inspect execution.json before continuing.'
            )
        session_file = artifacts / 'session.json'
        session = json.loads(session_file.read_text(encoding='utf-8')) if session_file.exists() else {}
        get_logger().info(f'ABC development {entry.case_id}: {result.status}; {result.error or artifacts}')
        return InferenceResult(
            output=ModelOutput.from_content(model.name, json.dumps(result.model_dump(), ensure_ascii=False)),
            trace=session_trace(session, result),
            messages=session_messages(session),
        )

    def match_score(
        self,
        original_prediction: str,
        filtered_prediction: str,
        reference: str,
        task_state: TaskState,
    ) -> Score:
        """Convert trusted verification evidence into native scores and report metadata."""
        if self is not None and self.coding.mode != 'develop':
            entry = CaseRecord(
                case_id=task_state.metadata['case_id'], case_manifest=task_state.metadata['case_manifest']
            )
            root, manifest = self._case(entry)
            execution = ExecutionResult.model_validate(task_state.metadata['execution'])
            output = Path(self.output_dir).resolve() / 'artifacts' / 'verification'
            result = verify(root, manifest, execution, output, baseline=self.coding.mode == 'verify_baseline')
            self._verifications.append(result.model_dump())
            scored = [r for r in self._verifications if r['resolved'] is not None]
            summary = {
                'attempts': self._verifications,
                'total': len(self._verifications),
                'valid': len(scored),
                'coverage': len(scored) / len(self._verifications),
                'resolved_rate': sum(r['resolved'] for r in scored) / len(scored) if scored else None,
                'infrastructure_errors': sum(r['status'] == 'infrastructure_error' for r in self._verifications),
                'needs_review': sum(r['status'] == 'needs_review' for r in self._verifications),
            }
            write_json(Path(self.output_dir) / 'artifacts/abc_coding/batch-verification.json', summary)
            values = {}
            if result.resolved is not None:
                values['resolved'] = result.resolved
                values.update({f'{group.lower()}_pass_rate': rate for group, rate in result.group_rates.items()})
            values['evaluation_coverage'] = int(result.resolved is not None)
            get_logger().info(
                f'ABC verification {entry.case_id}: {result.status}; {result.reason}; {result.artifact_dir}'
            )
            return Score(
                value=values,
                main_score_name='resolved',
                prediction=original_prediction,
                status=ScoreStatus.SUCCESS if result.resolved is not None else ScoreStatus.DEGRADED,
                explanation=result.reason,
                metadata={'verification': result.model_dump(), 'execution': execution.model_dump()},
            )
        return Score(
            value={},
            status=ScoreStatus.EXCLUDED,
            prediction=original_prediction,
            explanation='Development only; functional verifier has not run.',
            metadata={'functional_evaluation': 'not_run', 'execution': task_state.metadata.get('execution')},
        )
