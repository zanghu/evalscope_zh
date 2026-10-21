"""Contracts for local, development-only coding cases."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseRecord(BaseModel):
    """One row in the standard local JSONL dataset."""

    model_config = ConfigDict(extra='forbid')
    case_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
    case_manifest: str


class DevelopmentInput(BaseModel):
    """Files exposed to the agent; all paths are relative to the case root."""

    model_config = ConfigDict(extra='forbid')
    source_directory: str
    source_checksums: str
    working_directory: str = '.'
    task_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class VerificationStep(BaseModel):
    """One repository-owned command and optional machine-readable test report."""

    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=r'^[a-z][a-z0-9_-]*$')
    command: list[str] = Field(min_length=1)
    timeout: float = Field(default=300, gt=0)
    kind: Literal['setup', 'gate', 'tests']
    report_format: Literal['jest', 'junit'] | None = None
    report_path: str | None = None


class VerificationConfig(BaseModel):
    """Trusted case-specific verification recipe, independent of source language."""

    model_config = ConfigDict(extra='forbid')
    version: str
    working_directory: str
    overlay_manifest: str = 'verifier/overlay-manifest.json'
    test_inventory: str = 'verifier/test-inventory.json'
    environment: dict[str, str] = Field(default_factory=dict)
    ports: list[int] = Field(default_factory=list)
    steps: list[VerificationStep] = Field(min_length=1)


class CodingRunConfig(BaseModel):
    """Select development or replay without relying on prediction cache resume."""

    model_config = ConfigDict(extra='forbid')
    mode: Literal['develop', 'develop_and_verify', 'verify_only', 'verify_baseline'] = 'develop'
    candidates: dict[str, str] = Field(default_factory=dict)


class OverlayFile(BaseModel):
    """One trusted file mapped into the candidate workspace."""

    model_config = ConfigDict(extra='allow')
    package_path: str
    target_path: str
    sha256: str


class RequiredTest(BaseModel):
    """Stable test identity expected in a named verification stage."""

    model_config = ConfigDict(extra='allow')
    id: str
    suite: str
    group: str
    required: bool = True


class TestObservation(BaseModel):
    """Normalized result from a supported test reporter."""

    suite: str
    title: str
    status: Literal['passed', 'failed', 'error', 'skipped']
    detail: str = ''


class StageResult(BaseModel):
    """Command result with durable logs and no terminal I/O dependency."""

    name: str
    exit_code: int | None = None
    timed_out: bool = False
    duration_seconds: float = 0
    log_path: str
    report_path: str | None = None


class VerificationResult(BaseModel):
    """Evidence and scores for one immutable verification attempt."""

    verification_id: str
    case_id: str
    case_version: str
    development_attempt_id: str
    recipe_version: str = ''
    candidate_sha256: str = ''
    verifier_sha256: str = ''
    status: Literal['passed', 'failed', 'infrastructure_error', 'needs_review', 'budget_exceeded'] = 'needs_review'
    resolved: int | None = None
    group_rates: dict[str, float] = Field(default_factory=dict)
    stages: list[StageResult] = Field(default_factory=list)
    tests: list[TestObservation] = Field(default_factory=list)
    reason: str = ''
    artifact_dir: str
    duration_seconds: float = 0
    baseline: bool = False


class CaseManifest(BaseModel):
    """Development fields within the existing, extensible case manifest."""

    model_config = ConfigDict(extra='allow')
    case_id: str
    case_version: str
    task_file: str
    development: DevelopmentInput
    verification: VerificationConfig | None = None


class ExecutionResult(BaseModel):
    """Execution outcome, deliberately without a functional score."""

    case_id: str
    case_version: str = ''
    attempt_id: str
    status: Literal['completed', 'error', 'timed_out', 'needs_input', 'not_stopped'] = 'error'
    baseline_commit: str = ''
    session_id: str = ''
    provider_id: str = ''
    model_id: str = ''
    server_version: str = ''
    started_at: str
    duration_seconds: float = 0
    error: str | None = None
    artifact_dir: str
    workspace: str = ''
    source_manifest_sha256: str = ''
    task_sha256: str = ''
    functional_evaluation: Literal['not_run'] = 'not_run'
