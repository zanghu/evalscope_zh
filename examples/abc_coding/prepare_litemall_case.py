"""Prepare the litemall PR534 case described by the Python preparation guide.

The default action only builds and statically checks a NEW package.
Evaluation and model calls require an explicit action. Existing packages
are never overwritten by the prepare action.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

DEFAULT_PROMPT = (
    Path('E:/2024年10月01日codeABC任务')
    / '2026年03月16日部门研究课题企业级编程智能体'
    / 'litemall案例抽取实验'
    / 'PR_534生成PRD'
    / 'part1_prd_vision2web.md'
)


def write_json(path: Path, value: object) -> None:
    """Write UTF-8 JSON without a byte order mark."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    path.write_text(text + '\n', encoding='utf-8')


def sha256(path: Path) -> str:
    """Return the digest of a file's exact bytes."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> bytes:
    """Read or export committed Git data without switching branches."""
    result = subprocess.run(
        ['git', '-C', str(repo), *args],
        check=True,
        capture_output=True,
    )
    return result.stdout


def extract_zip(archive_path: Path, target: Path) -> None:
    """Reuse the adapter's safe extraction into a new directory."""
    from evalscope.benchmarks.abc_coding.verification import (
        extract_candidate,
    )

    extract_candidate(archive_path, target)


def prepare_case(
    bundle_root: Path,
    repo: Path,
    evalscope_repo: Path,
    prompt_file: Path,
    case_id: str,
) -> None:
    """Build a new package using sections 2-12, then run static checks."""
    from evalscope.benchmarks.abc_coding.contracts import CaseRecord

    CaseRecord(case_id=case_id, case_manifest=f'{case_id}/case.json')
    # 此处读取文件内容仅为提前校验，不是为了保存提示词内容
    #prompt_file.read_text(encoding='utf-8')
    assert prompt_file.is_file()
    for name in ('opencode.json', 'full.json', 'baseline.json'):
        template = evalscope_repo / 'examples/abc_coding' / name
        if not template.is_file():
            raise FileNotFoundError(template)
    dataset_root = bundle_root / 'evalscope_cases'
    config_root = bundle_root / 'configs'
    case_root = dataset_root / case_id
    stage_root = bundle_root / '_staging'
    runs_root = bundle_root / 'runs'
    if bundle_root.exists():
        raise FileExistsError('Choose a new bundle_root.')
    for folder in (
        config_root,
        stage_root,
        runs_root,
        case_root / 'source',
        case_root / 'verifier/config',
        case_root / 'validation',
        case_root / 'reference',
    ):
        folder.mkdir(parents=True, exist_ok=True)

    # Guide section 3.
    source_branch = 'benchmark_pr_534' # e94d1b3d66f9d6641326cf4469d9ef82c12e79ff
    tests_branch = 'benchmark_pr_534_finish_opencode_20260916_test' # 48d92b49b976c73d70d7add76bf0c0bd170b00d2
    # git -C 'E:\code\litemall' rev-parse benchmark_pr_534^{commit}
    # e94d1b3d66f9d6641326cf4469d9ef82c12e79ff
    # git -C 'E:\code\litemall' rev-parse benchmark_pr_534_finish_opencode_20260916_test^{commit}
    # 48d92b49b976c73d70d7add76bf0c0bd170b00d2
    # -C: 在执行 Git 命令之前，先切换到指定的目录。
    # rev-parse: 解析并输出 Git 对象（如提交、分支、标签等）的标识符（仓库内唯一）。目前 Git 内部默认使用的 SHA-1 哈希值。
    # ^{commit}: 剥壳语法（peel syntax），它告诉 Git 将该引用最终解析为提交对象。如果该引用指向的是一个标签（tag），并且这个标签指向另一个标签或树对象，^{commit} 会递归地剥开这些中间对象，直到得到最终的提交对象。
    # git rev-parse benchmark_pr_534^{commit}
    source_sha = (
        git(repo, 'rev-parse', source_branch + '^{commit}').decode().strip()
    )
    tests_sha = (
        git(repo, 'rev-parse', tests_branch + '^{commit}').decode().strip()
    )

    print('Initial commit:', source_sha)
    print('Tests commit:', tests_sha)

    """该段代码仅供人工核对，没有实际影响
    # git -C 'E:\code\litemall' diff e94d1b3d66f9d6641326cf4469d9ef82c12e79ff 48d92b49b976c73d70d7add76bf0c0bd170b00d2 -- 'litemall-admin/src/views/goods/list.vue'
    diff = git(
        repo,
        'diff',
        source_sha,
        tests_sha,
        '--',
        'litemall-admin/src/views/goods/list.vue',
    )
    print(diff.decode('utf-8', errors='replace'))
    """

    # Guide section 4. 创建起始代码压缩包，并“过滤式”解压
    initial_zip = case_root / 'source/initial.zip'
    # 生成压缩包 initial.zip
    # git -C 'E:\code\litemall' archive --format=zip --output='E:\custom_benchmark\evalscope_cases\litemall-pr534_prd\source\initial.zip' e94d1b3d66f9d6641326cf4469d9ef82c12e79ff
    # git archive 命令将 source_sha 指定的代码版本压缩为 initial.zip 压缩文件
    git(
        repo,
        'archive',
        '--format=zip',
        '--output=' + str(initial_zip),
        source_sha,
    )
    source_dir = case_root / 'source/initial'
    # 解压压缩包 initial.zip
    extract_zip(initial_zip, source_dir)

    # 验证解压后未生成`.git`目录
    if (source_dir / '.git').exists():
        raise ValueError('Initial source must not contain Git history.')

    # Guide section 5. 复制提示词文件到案例根目录
    task_path = case_root / 'task.md'
    #prompt_file.read_text(encoding='utf-8') # 去除重复检查
    shutil.copyfile(prompt_file, task_path)
    #assert task_path.read_bytes() == prompt_file.read_bytes() # 去除字节比对，如果真的要比对使用文件哈希值比对更合适

    # Guide section 6.
    # 此步骤实际在案例目录下生成以下两个部分的文件，这两个部分的文件（在 litemall 案例下）均是由案例来源项目中文件复制得到，不涉及自创新文件
    # 第1部分：case_root \verifier\tests，来源是 E:\code\litemall\litemall-admin\tests 目录
    # 第2部分：case_root \verifier\config，来源是 E:\code\litemall\litemall-admin\ 目录中，且包含于 configfiles 中的那些文件
    config_files = [
        'package.json',
        'package-lock.json',
        'jest.config.js',
        'babel.config.js',
        'playwright.config.ts',
        'vue.config.js',
        'postcss.config.js',
        'jsconfig.json',
        '.env.development',
        'scripts/serve-e2e.js',
    ]
    git_paths = ['litemall-admin/tests'] + [
        'litemall-admin/' + name for name in config_files
    ]
    trusted_zip = stage_root / 'trusted-files.zip'
    # 注意下面的 git archive 命令压缩时除了 config_files 中列出的文件之外，还包含了 litemall-admin/tests 整个目录
    # git -C 'E:\code\litemall' archive --format=zip --output='E:\custom_benchmark\evalscope_cases\_staging\trusted-files.zip' 48d92b49b976c73d70d7add76bf0c0bd170b00d2 -- \
    #     'litemall-admin/tests' \
    #     'litemall-admin/package.json' \
    #     'litemall-admin/jest.config.js' \
    #     ...
    git(
        repo,
        'archive',
        '--format=zip',
        '--output=' + str(trusted_zip),
        tests_sha,
        '--',
        *git_paths,
    )
    extract_zip(trusted_zip, stage_root / 'trusted')
    trusted_admin = stage_root / 'trusted/litemall-admin'
    shutil.copytree(
        trusted_admin / 'tests',
        case_root / 'verifier/tests',
    )
    for name in config_files:
        target = case_root / 'verifier/config' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(trusted_admin / name, target)

    # 变更原始 e2e 测试用例中的成功验证标识，增强验证的可靠性，但即使如此仍不能完全避免“假阳性”问题。
    spec_path = case_root / 'verifier/tests/e2e/goods-list.spec.ts'
    original = spec_path.read_bytes().decode('utf-8')
    marker = "test.describe('P2P"
    f2p, p2p = original.split(marker, 1)
    old_assertion = (
        "await expect(page.getByText('删除成功', "
        '{ exact: true }).first()).toBeVisible()'
    )
    new_assertion = (
        'await expect(page.locator('
        "'.el-notification:has(.el-icon-success)'"
        ').first()).toBeVisible()'
    )
    if f2p.count(old_assertion) != 2:
        raise ValueError('Review changed upstream test assertions.')
    revised = f2p.replace(old_assertion, new_assertion) + marker + p2p
    spec_path.write_bytes(revised.encode('utf-8'))

    # Guide section 7.
    source_hashes = {
        path.relative_to(source_dir).as_posix(): sha256(path)
        for path in sorted(source_dir.rglob('*'))
        if path.is_file()
    }
    write_json(
        case_root / 'validation/source-files.json',
        source_hashes,
    )

    overlay = []
    for section in ('tests', 'config'):
        base = case_root / 'verifier' / section
        for path in sorted(base.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(base).as_posix()
            prefix = 'litemall-admin/'
            if section == 'tests':
                prefix += 'tests/'
            target = prefix + relative
            entry = {
                'package_path': f'verifier/{section}/{relative}',
                'target_path': target,
                'sha256': sha256(path),
                'source_commit': tests_sha,
                'source_path': target,
            }
            if path == spec_path:
                upstream = trusted_admin / 'tests/e2e/goods-list.spec.ts'
                entry['upstream_sha256'] = sha256(upstream)
                entry['local_modification'] = (
                    'F2P-E02/E03 accept success notification wording.'
                )
            overlay.append(entry)

    if len(overlay) != 16:
        raise ValueError('Expected 16 trusted files; review export.')
    write_json(case_root / 'verifier/overlay-manifest.json', overlay)
    task_hash = sha256(task_path)

    # Guide section 8.
    groups = [
        ('unit', 'F2P', 'F2P-U', 2),
        ('unit', 'P2P', 'P2P-U', 7),
        ('e2e', 'F2P', 'F2P-E', 4),
        ('e2e', 'P2P', 'P2P-E', 6),
    ]
    inventory = []
    for suite, group, prefix, max_id in groups:
        for number in range(1, max_id + 1):
            inventory.append(
                {
                    'id': f'{prefix}{number:02d}',
                    'suite': suite,
                    'group': group,
                    'required': True,
                }
            )
    write_json(case_root / 'verifier/test-inventory.json', inventory)

    # Guide section 9.
    steps = [
        {
            'name': 'install',
            'kind': 'setup',
            'timeout': 1200,
            'command': ['npm', 'ci', '--no-audit', '--no-fund'],
        },
        {
            'name': 'types',
            'kind': 'gate',
            'timeout': 180,
            'command': ['npm', 'run', 'test:types'],
        },
        {
            'name': 'unit',
            'kind': 'tests',
            'timeout': 300,
            'command': [
                'npm',
                'run',
                'test:unit',
                '--',
                '--json',
                '--outputFile=unit-results.json',
            ],
            'report_format': 'jest',
            'report_path': 'unit-results.json',
        },
        {
            'name': 'e2e',
            'kind': 'tests',
            'timeout': 900,
            'command': ['npm', 'run', 'test:e2e'],
            'report_format': 'junit',
            'report_path': 'test-results/e2e.xml',
        },
    ]
    case = {
        'schema_version': '0.1.0',
        'case_id': case_id,
        'case_version': '1.0.0',
        'evaluation_version': '1.2.0',
        'title': 'litemall 管理后台商品批量删除（完整版 PRD）',
        'task_file': 'task.md',
        'source_archive': 'source/initial.zip',
        'source_branch': source_branch,
        'source_commit': source_sha,
        'tests_commit': tests_sha,
        'development': {
            'source_directory': 'source/initial',
            'source_checksums': 'validation/source-files.json',
            'working_directory': '.',
            'task_sha256': task_hash,
        },
        'verification': {
            'version': '1.1.0',
            'working_directory': 'litemall-admin',
            'overlay_manifest': 'verifier/overlay-manifest.json',
            'test_inventory': 'verifier/test-inventory.json',
            'environment': {
                'CI': 'true',
                'NODE_OPTIONS': '--openssl-legacy-provider',
                'PLAYWRIGHT_CHANNEL': 'chrome',
            },
            'ports': [9528],
            'steps': steps,
        },
        'reference': {'directory': 'reference', 'available': False},
    }
    write_json(case_root / 'case.json', case)

    # Guide section 10.
    notes = {
        'README.md': (
            '# litemall PR #534 完整版 PRD 案例\n\n'
            f'案例 ID：{case_id}。来源详见 validation/provenance.json。\n'
            '仅完成资料整理；尚未运行本包的校准、开发或验收。\n'
            '只向智能体提供需求和起始源码，不提供可信测试。\n'
        ),
        'ENVIRONMENT.md': (
            '# 环境\n\n'
            'Windows；已验证组合 Node 22.14.0、npm 10.9.2。\n'
            '需预装 Git、当前 EvalScope Python 环境、OpenCode 和 Chrome。\n'
            '验收前端 API 由 fixtures 模拟，不要求 Java 或 MySQL。\n'
            '测试端口 9528，OpenCode 41960，报告 UI 默认 9000。\n'
            '锁文件镜像需可达；验收在独立目录执行 npm ci。\n'
            '浏览器与 Vue 服务由 Playwright 配置启动并等待就绪。\n'
            '模型凭据不得写入案例包；本地工作区不是系统沙箱。\n'
        ),
        'SCORING.md': (
            '# 评分说明\n\n'
            '类型检查与全部 19 项测试通过时 resolved=1。\n'
            '证据完整且存在明确断言失败时 resolved=0。\n'
            '验收证据缺失或异常无法判定时单列，不冒充功能失败。\n'
            '开发超预算按当前适配器记 budget_exceeded、resolved=0。\n'
            'F2P 共 6 项、P2P 共 13 项，另报有效评估覆盖率。\n'
            '验收版本 1.1.0：E02/E03 接受不同的成功通知文案。\n'
            '测试通过不表示完整 PRD 的所有条目均已被测试覆盖。\n'
        ),
    }
    for name, text in notes.items():
        (case_root / name).write_text(text, encoding='utf-8')

    provenance = {
        'packaged_on': date.today().isoformat(),
        'case_id': case_id,
        'local_repository': str(repo),
        'source_branch': source_branch,
        'source_commit': source_sha,
        'tests_branch': tests_branch,
        'tests_commit': tests_sha,
        'prompt_source': str(prompt_file),
        'test_assertions_modified': True,
        'modified_tests': ['F2P-E02', 'F2P-E03'],
        'tests_added': False,
        'reference_included': False,
        'validation_status': 'not_run_for_this_package',
    }
    write_json(case_root / 'validation/provenance.json', provenance)

    # Guide section 11.
    checksum_path = case_root / 'validation/checksums.json'
    package_hashes = {}
    for path in sorted(case_root.rglob('*')):
        if path.is_file() and path != checksum_path:
            relative = path.relative_to(case_root).as_posix()
            package_hashes[relative] = sha256(path)
    write_json(checksum_path, package_hashes)

    # Guide section 12.
    index_path = dataset_root / 'default_test.jsonl'
    row = {
        'case_id': case_id,
        'case_manifest': f'{case_id}/case.json',
    }
    index_path.write_text(
        json.dumps(row, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )

    templates = {
        'opencode.json': 'abc-coding-opencode.json',
        'full.json': 'abc-coding-full.json',
        'baseline.json': 'abc-coding-baseline.json',
    }
    for template_name, output_name in templates.items():
        source = evalscope_repo / 'examples/abc_coding' / template_name
        config = json.loads(source.read_text(encoding='utf-8'))
        args = config['dataset_args']['abc_coding']
        args['local_path'] = dataset_root.as_posix()
        config['work_dir'] = runs_root.as_posix()
        write_json(config_root / output_name, config)

    check_case(case_root)
    print(f'Package created: {case_root}')
    print('No agent or tests were invoked.')


def check_case(case_root: Path) -> None:
    """Validate one package without starting a model or test process."""
    case_id = case_root.name
    task_path = case_root / 'task.md'
    source_dir = case_root / 'source/initial'
    initial_zip = case_root / 'source/initial.zip'
    index_path = case_root.parent / 'default_test.jsonl'
    from evalscope.benchmarks.abc_coding.contracts import (
        CaseManifest,
        CaseRecord,
        OverlayFile,
        RequiredTest,
    )

    manifest = CaseManifest.model_validate_json(
        (case_root / 'case.json').read_bytes()
    )
    records = [
        CaseRecord.model_validate_json(line)
        for line in index_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert len({row.case_id for row in records}) == len(records)
    matching = [row for row in records if row.case_id == case_id]
    assert len(matching) == 1
    assert manifest.case_id == case_id
    assert matching[0].case_manifest == f'{case_id}/case.json'
    assert sha256(task_path) == manifest.development.task_sha256

    saved_sources = json.loads(
        (case_root / 'validation/source-files.json').read_bytes()
    )
    actual_sources = {
        path.relative_to(source_dir).as_posix(): sha256(path)
        for path in sorted(source_dir.rglob('*'))
        if path.is_file()
    }
    assert actual_sources == saved_sources
    with zipfile.ZipFile(initial_zip) as archive:
        archived = {
            info.filename: hashlib.sha256(
                archive.read(info.filename)
            ).hexdigest()
            for info in archive.infolist()
            if not info.is_dir()
        }
    assert archived == actual_sources

    overlay_path = case_root / manifest.verification.overlay_manifest
    for raw in json.loads(overlay_path.read_bytes()):
        item = OverlayFile.model_validate(raw)
        assert sha256(case_root / item.package_path) == item.sha256

    inventory_path = case_root / manifest.verification.test_inventory
    items = [
        RequiredTest.model_validate(raw)
        for raw in json.loads(inventory_path.read_bytes())
    ]
    assert len(items) == 19
    assert len({item.id for item in items}) == 19
    assert {item.suite for item in items} == {'unit', 'e2e'}

    checksum_path = case_root / 'validation/checksums.json'
    if checksum_path.exists():
        for name, expected in json.loads(checksum_path.read_bytes()).items():
            assert sha256(case_root / name) == expected, name
    print('Static checks passed; no model or tests were run.')


def run_eval(bundle_root: Path, evalscope_repo: Path, name: str) -> None:
    """Invoke an explicitly selected EvalScope configuration."""
    subprocess.run(
        [
            sys.executable,
            '-m',
            'evalscope.cli.cli',
            'eval',
            '--task-config',
            str(bundle_root / 'configs' / name),
        ],
        cwd=evalscope_repo,
        check=True,
    )


def prepare_replay(
    bundle_root: Path,
    case_id: str,
    candidate_dir: Path,
) -> None:
    """Create a replay config after checking candidate input identity."""
    config_path = bundle_root / 'configs/abc-coding-verify.json'
    if config_path.exists():
        raise FileExistsError(config_path)
    for name in ('execution.json', 'candidate.json', 'candidate.zip'):
        if not (candidate_dir / name).is_file():
            raise FileNotFoundError(candidate_dir / name)
    case_root = bundle_root / 'evalscope_cases' / case_id
    case = json.loads((case_root / 'case.json').read_bytes())
    execution = json.loads((candidate_dir / 'execution.json').read_bytes())
    development = case['development']
    expected = {
        'case_id': case_id,
        'case_version': case['case_version'],
        'task_sha256': development['task_sha256'],
        'source_manifest_sha256': sha256(
            case_root / development['source_checksums']
        ),
    }
    for field, value in expected.items():
        if execution[field] != value:
            raise ValueError(f'Candidate identity mismatch: {field}')
    source = bundle_root / 'configs/abc-coding-baseline.json'
    config = json.loads(source.read_bytes())
    config['model'] = execution['model_id'] + '-opencode'
    config['dataset_args']['abc_coding']['extra_params']['coding'] = {
        'mode': 'verify_only',
        'candidates': {case_id: str(candidate_dir)},
    }
    index = bundle_root / 'evalscope_cases/default_test.jsonl'
    rows = [
        json.loads(line)
        for line in index.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    if [row['case_id'] for row in rows] != [case_id]:
        raise ValueError('Replay setup requires a single-case index.')
    write_json(config_path, config)
    print(f'Replay config created: {config_path}')


def main() -> None:
    """Dispatch packaging, checks, and explicit runtime actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'action',
        nargs='?',
        default='prepare',
        choices=[
            'prepare',
            'check',
            'baseline',
            'develop',
            'full',
            'replay-config',
            'verify',
            'service',
        ],
    )
    parser.add_argument(
        '--bundle-root',
        type=Path,
        default=Path('E:/custom_benchmark_manual_python'),
    )
    parser.add_argument(
        '--repo',
        type=Path,
        default=Path('E:/code/litemall'),
    )
    parser.add_argument(
        '--evalscope-repo',
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument('--prompt-file', type=Path, default=DEFAULT_PROMPT)
    parser.add_argument('--case-id', default='litemall-pr534_prd')
    parser.add_argument('--candidate-dir', type=Path)
    args = parser.parse_args()
    # Prefer the requested checkout over an older installed EvalScope.
    sys.path.insert(0, str(args.evalscope_repo.resolve()))
    if not __debug__:
        parser.error('Do not use python -O: static checks use assert.')
    bundle_root = args.bundle_root.resolve()
    case_root = bundle_root / 'evalscope_cases' / args.case_id
    if args.action == 'prepare':
        prepare_case(
            bundle_root,
            args.repo.resolve(),
            args.evalscope_repo.resolve(),
            args.prompt_file,
            args.case_id,
        )
        return
    if args.action == 'check':
        check_case(case_root)
        return
    if args.action == 'replay-config':
        if args.candidate_dir is None:
            parser.error('replay-config requires --candidate-dir')
        prepare_replay(bundle_root, args.case_id, args.candidate_dir)
        return
    if args.action == 'service':
        subprocess.run(
            [
                sys.executable,
                '-m',
                'evalscope.cli.cli',
                'service',
                '--host',
                '127.0.0.1',
                '--outputs',
                str(bundle_root / 'runs'),
            ],
            cwd=args.evalscope_repo,
            check=True,
        )
        return
    configurations = {
        'baseline': 'abc-coding-baseline.json',
        'develop': 'abc-coding-opencode.json',
        'full': 'abc-coding-full.json',
        'verify': 'abc-coding-verify.json',
    }
    run_eval(
        bundle_root,
        args.evalscope_repo,
        configurations[args.action],
    )


if __name__ == '__main__':
    main()
