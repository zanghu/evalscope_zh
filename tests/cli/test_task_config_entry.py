import argparse
import importlib
from pathlib import Path

import pytest

from evalscope.cli.start_eval import EvalCMD
from evalscope.config import parse_task_config


def test_task_config_uses_existing_file_parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / 'task.json'
    config.write_text('{"model":"configured-model","eval_type":"mock_llm","datasets":["abc_coding"]}',
                      encoding='utf-8')
    seen = []
    monkeypatch.setattr(importlib.import_module('evalscope.run'), 'run_task',
                        lambda value: seen.append(parse_task_config(value)))
    parser = argparse.ArgumentParser()
    EvalCMD.define_args(parser.add_subparsers())
    args = parser.parse_args(['eval', '--task-config', str(config)])
    EvalCMD(args).execute()
    assert seen[0].datasets == ['abc_coding']
    assert seen[0].model == 'configured-model'


def test_backend_config_cannot_be_mixed_with_task_config() -> None:
    parser = argparse.ArgumentParser()
    EvalCMD.define_args(parser.add_subparsers())
    args = parser.parse_args(['eval', '--task-config', 'task.json', '--eval-config', 'backend.json'])
    with pytest.raises(ValueError, match='not both'):
        EvalCMD(args).execute()
