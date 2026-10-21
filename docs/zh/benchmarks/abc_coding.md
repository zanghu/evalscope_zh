# ABC Coding


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


## Properties

| Property | Value |
|----------|-------|
| **Benchmark Name** | `abc_coding` |
| **Dataset ID** | `abc_coding` |
| **Paper** | N/A |
| **Tags** | `Agent`, `Coding`, `Custom` |
| **Metrics** | `resolved`, `f2p_pass_rate`, `p2p_pass_rate`, `evaluation_coverage` |
| **Default Shots** | 0-shot |
| **Evaluation Split** | `test` |


## Data Statistics

*Statistics not available.*

## Sample Example

*Sample example not available.*

## Prompt Template

**Prompt Template:**
```text
{question}
```

## Extra Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `opencode` | `dict` | `{}` | OpenCodeHTTPConfig connection and policy. |
| `coding` | `dict` | `{}` | CodingRunConfig mode and candidate directories. |

## Usage

### Using CLI

```bash
evalscope eval \
    --model YOUR_MODEL \
    --api-url OPENAI_API_COMPAT_URL \
    --api-key EMPTY_TOKEN \
    --datasets abc_coding \
    --limit 10  # Remove this line for formal evaluation
```

### Using Python

```python
from evalscope import run_task
from evalscope.config import TaskConfig

task_cfg = TaskConfig(
    model='YOUR_MODEL',
    api_url='OPENAI_API_COMPAT_URL',
    api_key='EMPTY_TOKEN',
    datasets=['abc_coding'],
    dataset_args={
        'abc_coding': {
            # extra_params: {}  # uses default extra parameters
        }
    },
    limit=10,  # Remove this line for formal evaluation
)

run_task(task_cfg=task_cfg)
```
