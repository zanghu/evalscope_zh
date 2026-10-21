# ABC Coding 案例包手工整理说明（Python 版）

本文是 `abc_coding_case_preparation.md` 的独立新版，不覆盖旧文档。
以 litemall PR #534 为例，介绍如何从 Git 分支、需求文件与测试资料生成当前
`abc_coding` 适配器需要的输入。所有文件生成操作均使用 Python；代码行不超过
80 个字符。适用范围是当前仓库实现，不是所有 EvalScope 基准的统一格式。

本版采用已确认的完整版 `part1_prd_vision2web.md`，案例 ID 为
`litemall-pr534_prd`。现有简版案例 `litemall-pr534` 应继续保留，不能覆盖。
下面默认在新目录 `E:\custom_benchmark_manual_python` 演练，不写正式案例目录。

可直接调用的整理版脚本位于
[`examples/abc_coding/prepare_litemall_case.py`](../../../examples/abc_coding/prepare_litemall_case.py)。
脚本使用与本文相同的文件生成逻辑，默认仅打包及静态检查；通过 `--help` 查看
各动作。`prepare` 要求目标根目录不存在，`check` 只检查已有包；`baseline`、
`develop`、`full`、`verify` 和 `service` 是显式执行动作。
`replay-config` 仅生成重验配置，不立即执行重验。

各节中的“必需”指当前适配器在对应运行模式下需要的输入；“可选”表示缺失不影响
相应自动化流程；“临时”表示只用于本文制作过程，完成后不需要随案例发布。
必需输入与运行后生成的输出不是同一概念，后者单独标为“运行产物”。

## 1. 输入资料、路径记号与执行方式

**本节生成文件：无。** 以下均为已有输入，不需要生成新文件。

| 输入 | 路径或取值 |
|---|---|
| Git 仓库 | `E:\code\litemall` |
| 起始分支 | `benchmark_pr_534` |
| 测试分支 | `benchmark_pr_534_finish_opencode_20260916_test` |
| 正确需求文件 | `E:\2024年10月01日codeABC任务\2026年03月16日部门研究课题企业级编程智能体\litemall案例抽取实验\PR_534生成PRD\part1_prd_vision2web.md` |
| EvalScope 仓库 | `E:\code\evalscope` |

旧文档使用的是简版 `part1_prompt_vision2web.txt`；本版不使用它。起始分支不能
误用 `benchmark_pr_534_init`，该分支已包含目标功能。测试分支也含有解决方案，
只能按白名单导出可信测试和配置，不能整库复制作为起始输入。

本文统一以下路径记号，后文每个生成文件的路径均按这些记号展开：

| 记号 | 默认绝对路径 |
|---|---|
| B | `E:\custom_benchmark_manual_python` |
| D | `B\evalscope_cases` |
| C | `D\litemall-pr534_prd` |
| K | `B\configs` |
| S | `B\_staging` |
| R | `B\runs` |

例如 `C\task.md` 的完整路径为
`E:\custom_benchmark_manual_python\evalscope_cases\litemall-pr534_prd\task.md`。

使用安装了当前 EvalScope 的 Python 3.10 或以上环境。第 2～13 节的 Python
代码共享变量，可在同一个交互会话中按顺序执行，或按顺序复制到一个自行保存的
脚本中执行；各节不是彼此独立的脚本。第 14～16 节是可选运行操作，需要继续沿用
这些变量，并按说明选择执行。不要一次性执行本文全部代码来尝试重建现有正式包。

## 2. 建立目录和公共辅助函数

**本节生成文件：无。** 仅新建 B、D、C、K、S、R 和 C 内的子目录。
`C\reference` 是可选空占位目录，不是文件；S 是临时目录，R 保存运行产物。
其他子目录用于后续必需文件。`validation` 不能整体视为可选：其中源文件清单是
开发阶段必需输入，而来源说明和包级清单是可选的管理资料。

若 B 已存在，代码主动报错。请改用另一个新目录，不要自动删除已有目录。

```python
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

repo = Path('E:/code/litemall')
evalscope_repo = Path('E:/code/evalscope')
bundle_root = Path('E:/custom_benchmark_manual_python')
dataset_root = bundle_root / 'evalscope_cases'
config_root = bundle_root / 'configs'
case_id = 'litemall-pr534_prd'
case_root = dataset_root / case_id
stage_root = bundle_root / '_staging'
runs_root = bundle_root / 'runs'
prompt_file = (
    Path('E:/2024年10月01日codeABC任务')
    / '2026年03月16日部门研究课题企业级编程智能体'
    / 'litemall案例抽取实验'
    / 'PR_534生成PRD'
    / 'part1_prd_vision2web.md'
)

if bundle_root.exists():
    raise FileExistsError('Choose a new bundle_root.')

for folder in (
    config_root, stage_root, runs_root,
    case_root / 'source', case_root / 'verifier/config',
    case_root / 'validation', case_root / 'reference',
):
    folder.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    path.write_text(text + '\n', encoding='utf-8')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> bytes:
    result = subprocess.run(
        ['git', '-C', str(repo), *args],
        check=True, capture_output=True,
    )
    return result.stdout


def extract_zip(archive_path: Path, target: Path) -> None:
    from evalscope.benchmarks.abc_coding.verification import (
        extract_candidate,
    )
    extract_candidate(archive_path, target)
```

`write_json` 创建或覆盖一个 JSON 文件，UTF-8 无 BOM。变量中的字典不是另外的
文件。解压复用现有适配器的安全解压函数，目标目录必须不存在。

## 3. 解析并确认固定提交

**本节生成文件：无。** `source_sha`、`tests_sha` 只是内存中的字符串，后续
写入案例描述和来源记录。命令只读取本地提交，不切换分支、不包含未提交修改。

```python
source_branch = 'benchmark_pr_534'
tests_branch = 'benchmark_pr_534_finish_opencode_20260916_test'
source_sha = git(
    'rev-parse', source_branch + '^{commit}'
).decode().strip()
tests_sha = git(
    'rev-parse', tests_branch + '^{commit}'
).decode().strip()

print('Initial commit:', source_sha)
print('Tests commit:', tests_sha)
diff = git(
    'diff', source_sha, tests_sha, '--',
    'litemall-admin/src/views/goods/list.vue',
)
print(diff.decode('utf-8', errors='replace'))
```

截至本案例准备时，起始提交是
`e94d1b3d66f9d6641326cf4469d9ef82c12e79ff`，测试提交是
`48d92b49b976c73d70d7add76bf0c0bd170b00d2`。若解析结果变化，先检查差异，不要
默认新分支头与已验证版本等价。人工确认起始代码缺少批量删除功能、原有单条删除
等行为仍存在；第 14 节的基线校准会进一步验证。

## 4. 导出起始代码

**本节生成文件：**

| 输出路径 | 必需性 | 用途 |
|---|---|---|
| `C\source\initial.zip` | 基线校准必需；本规范保留 | 固定提交归档，无 Git 历史 |
| `C\source\initial\**\*` | 开发模式必需 | ZIP 内所有源码文件的展开副本 |

```python
initial_zip = case_root / 'source/initial.zip'
git(
    'archive', '--format=zip',
    '--output=' + str(initial_zip), source_sha,
)
source_dir = case_root / 'source/initial'
extract_zip(initial_zip, source_dir)

if (source_dir / '.git').exists():
    raise ValueError('Initial source must not contain Git history.')
```

ZIP 根层直接包含 `litemall-admin` 和其他项目模块，不额外套仓库文件夹。
不要向 initial 注入验收测试、安装依赖或运行构建。ZIP 与展开目录必须来自同一
快照：当前开发读取目录，`verify_baseline` 读取 ZIP。执行器自行创建新的 Git
基线，不需要在案例包内初始化 Git。

其他项目若使用 LFS、子模块或 `export-ignore`，需额外审核归档完整性。

## 5. 复制完整版需求

**本节生成文件：`C\task.md`，必需。** 它是实际发送给智能体的需求正文。

```python
task_path = case_root / 'task.md'
prompt_file.read_text(encoding='utf-8')
shutil.copyfile(prompt_file, task_path)
assert task_path.read_bytes() == prompt_file.read_bytes()
```

这里复制原始字节，不重写需求内容。文件必须可按 UTF-8 读取。需求改动意味着
任务输入变化，需要更新任务哈希及案例版本；旧候选不能直接当作新任务的结果。

## 6. 提取可信测试和配置，修正两处断言

**本节生成文件：**

| 输出路径 | 必需性 |
|---|---|
| `S\trusted-files.zip` | 临时，仅供本节解压 |
| `S\trusted\litemall-admin\…` | 临时，16 个原始验收文件 |
| `C\verifier\tests\…` | 验收必需，具体 6 个文件见下表 |
| `C\verifier\config\…` | 验收必需，本案例选定的 10 个配置文件 |

这里的“必需”指本文完整覆盖清单会引用它们。`tests/README.md` 本身不执行测试，
可以在另行修订覆盖清单的规范中省略；但不能从已生成包中单独删除而不更新清单。

| 包内相对路径 | 对应仓库路径 |
|---|---|
| `verifier/tests/README.md` | `litemall-admin/tests/README.md` |
| `verifier/tests/e2e/fixtures.ts` | `litemall-admin/tests/e2e/fixtures.ts` |
| `verifier/tests/e2e/goods-list.spec.ts` | `litemall-admin/tests/e2e/goods-list.spec.ts` |
| `verifier/tests/unit/goods-list.spec.ts` | `litemall-admin/tests/unit/goods-list.spec.ts` |
| `verifier/tests/tsconfig.json` | `litemall-admin/tests/tsconfig.json` |
| `verifier/tests/vue.d.ts` | `litemall-admin/tests/vue.d.ts` |
| `verifier/config/package.json` | `litemall-admin/package.json` |
| `verifier/config/package-lock.json` | `litemall-admin/package-lock.json` |
| `verifier/config/jest.config.js` | `litemall-admin/jest.config.js` |
| `verifier/config/babel.config.js` | `litemall-admin/babel.config.js` |
| `verifier/config/playwright.config.ts` | `litemall-admin/playwright.config.ts` |
| `verifier/config/vue.config.js` | `litemall-admin/vue.config.js` |
| `verifier/config/postcss.config.js` | `litemall-admin/postcss.config.js` |
| `verifier/config/jsconfig.json` | `litemall-admin/jsconfig.json` |
| `verifier/config/.env.development` | `litemall-admin/.env.development` |
| `verifier/config/scripts/serve-e2e.js` | `litemall-admin/scripts/serve-e2e.js` |

```python
config_files = [
    'package.json', 'package-lock.json', 'jest.config.js',
    'babel.config.js', 'playwright.config.ts', 'vue.config.js',
    'postcss.config.js', 'jsconfig.json', '.env.development',
    'scripts/serve-e2e.js',
]
git_paths = ['litemall-admin/tests'] + [
    'litemall-admin/' + name for name in config_files
]
trusted_zip = stage_root / 'trusted-files.zip'
git(
    'archive', '--format=zip',
    '--output=' + str(trusted_zip), tests_sha, '--', *git_paths,
)
extract_zip(trusted_zip, stage_root / 'trusted')
trusted_admin = stage_root / 'trusted/litemall-admin'
shutil.copytree(
    trusted_admin / 'tests', case_root / 'verifier/tests',
)
for name in config_files:
    target = case_root / 'verifier/config' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(trusted_admin / name, target)

spec_path = case_root / 'verifier/tests/e2e/goods-list.spec.ts'
original = spec_path.read_bytes().decode('utf-8')
marker = "test.describe('P2P"
f2p, p2p = original.split(marker, 1)
old_assertion = (
    "await expect(page.getByText('删除成功', "
    "{ exact: true }).first()).toBeVisible()"
)
new_assertion = (
    "await expect(page.locator("
    "'.el-notification:has(.el-icon-success)'"
    ").first()).toBeVisible()"
)
if f2p.count(old_assertion) != 2:
    raise ValueError('Review changed upstream test assertions.')
revised = f2p.replace(old_assertion, new_assertion) + marker + p2p
spec_path.write_bytes(revised.encode('utf-8'))
```

这会修改刚复制的 F2P-E02/E03 成功提示断言，检查可见成功通知而不限制完整文案，
不修改 P2P 断言或其他行为检查。测试源文件中的代码排版保持原样；上述 Python
代码本身每行均不超过 80 字符。

不提取业务 `src/views/goods/list.vue` 或语言资源中的解决方案。配置也需人工
审核，确认只负责测试与构建、不内嵌功能答案。fixtures 模拟登录和 API，当前
验收不要求真实 Java 后端或 MySQL。

## 7. 生成源码清单与可信覆盖清单

**本节生成两个文件，均必需：**

| 输出路径 | 用途 |
|---|---|
| `C\validation\source-files.json` | 开发阶段核对源码目录的完整文件集合和哈希 |
| `C\verifier\overlay-manifest.json` | 验收时复制可信文件，并校验最终字节 |

```python
source_hashes = {
    path.relative_to(source_dir).as_posix(): sha256(path)
    for path in sorted(source_dir.rglob('*')) if path.is_file()
}
write_json(
    case_root / 'validation/source-files.json', source_hashes,
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
```

`source_hashes`、`overlay`、`task_hash` 都是内存变量，不是另外的文件。
覆盖清单不是候选业务代码与参考实现的比较清单；它只描述可信验收文件的注入。

## 8. 编制必须执行的测试结果清单

**本节生成文件：`C\verifier\test-inventory.json`，验收评分必需。**

| 测试步骤 | F2P | P2P | 合计 |
|---|---|---|---|
| unit | F2P-U01～U02 | P2P-U01～U07 | 9 |
| e2e | F2P-E01～E04 | P2P-E01～E06 | 10 |
| 总计 | 6 | 13 | 19 |

```python
groups = [
    ('unit', 'F2P', 'F2P-U', 2),
    ('unit', 'P2P', 'P2P-U', 7),
    ('e2e', 'F2P', 'F2P-E', 4),
    ('e2e', 'P2P', 'P2P-E', 6),
]
inventory = []
for suite, group, prefix, max_id in groups:
    for number in range(1, max_id + 1):
        inventory.append({
            'id': f'{prefix}{number:02d}',
            'suite': suite,
            'group': group,
            'required': True,
        })
write_json(case_root / 'verifier/test-inventory.json', inventory)
```

这个脚本只生成四个字段，**不会生成 `title`**，也没有后续步骤偷偷增加它。
与现有包的含 title 版本相比，输出在字节和字段上不同，但当前匹配与分组评分
语义相同。清单的 title 是可选说明字段；需要时可以显式补充，但不必为了运行添加。

自动化职责如下：

- `case.json` 的步骤命令启动整个套件；Jest/Playwright 配置决定测试文件位置。
- 报告解析产生实际测试名称，`grade()` 用清单的 `suite` 和 `id` 匹配报告。
- 要求报告名称包含完整 ID、同一步骤中唯一匹配；不比较清单 title 的完整文案。
- 缺失、重复、跳过或错误的必需结果导致待确认；不会仅凭命令退出码 0 判定成功。
- `group` 决定 F2P/P2P 分组；类型检查另设 gate，不占 19 项测试数量。

这里的 suite 是第 9 节步骤名。它不是文件路径，也不是 Jest 的 describe 名称。
不要从一次实际报告反向生成清单，否则漏跑的用例可能从要求中一起消失。

## 9. 生成案例描述与验收执行配方

**本节生成文件：`C\case.json`，必需。** 下面是足够当前适配器使用的描述，
不复制旧包中已经过时的历史校准声明。

```python
steps = [
    {
        'name': 'install', 'kind': 'setup', 'timeout': 1200,
        'command': ['npm', 'ci', '--no-audit', '--no-fund'],
    },
    {
        'name': 'types', 'kind': 'gate', 'timeout': 180,
        'command': ['npm', 'run', 'test:types'],
    },
    {
        'name': 'unit', 'kind': 'tests', 'timeout': 300,
        'command': [
            'npm', 'run', 'test:unit', '--', '--json',
            '--outputFile=unit-results.json',
        ],
        'report_format': 'jest',
        'report_path': 'unit-results.json',
    },
    {
        'name': 'e2e', 'kind': 'tests', 'timeout': 900,
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
```

资源路径相对 C；覆盖 target_path 相对候选仓库根；report_path 相对验收工作
目录。开发从完整仓库根开始，验收命令在 litemall-admin 执行。不要在 command
内拼接 shell 操作符。当前运行读取 verification.steps，不依赖人可读说明中的
命令，也不依赖历史包的 execution.commands 字段。

本例保留当前验收版本语义。不同项目需独立确定版本、命令和测试报告格式；当前
解析器支持 Jest JSON 与 JUnit XML。生成的新包不等于历史包逐字重建，尤其源清单
的序列化差异也可能影响身份哈希；勿改写历史候选元数据来绕过身份检查。

## 10. 生成人可读说明与来源记录（可选）

**本节生成 4 个可选文件：**

| 输出路径 | 功能 |
|---|---|
| `C\README.md` | 人工阅读入口、来源与状态 |
| `C\ENVIRONMENT.md` | 工具、依赖、端口和测试范围 |
| `C\SCORING.md` | 当前评分逻辑的说明 |
| `C\validation\provenance.json` | 固定提交、需求来源与本地修改记录 |

不生成它们不影响适配器运行。执行器不会通过阅读这些文档来安装工具或更改评分。
但建议发布案例时保留。没有运行过校准时不得写成已经通过。

```python
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
```

如果跳过本节，第 11 节自然不会收录这些文件。若先生成清单再删除说明文件，则需
更新包级清单。历史包的 verifier/prepare.ps1 是可选工具，本版不生成它；后续
通过正式 verify_baseline 模式进行校准。

## 11. 生成包级校验清单（可选）

**本节只生成一个文件：`C\validation\checksums.json`，可选。**
当前适配器不主动逐项读取这份包级清单，关键运行校验使用第 7 节的源清单、覆盖
清单和 case.json 中的任务哈希。本文保留包级清单供人工交付检查；第 13 节在它
存在时会进行核对。

```python
checksum_path = case_root / 'validation/checksums.json'
package_hashes = {}
for path in sorted(case_root.rglob('*')):
    if path.is_file() and path != checksum_path:
        relative = path.relative_to(case_root).as_posix()
        package_hashes[relative] = sha256(path)
write_json(checksum_path, package_hashes)
```

`package_hashes` 是内存字典，不是新文件。必须排除输出文件自身，避免自引用。
README 或来源记录后续变化时重做本节；可信测试变化还需更新覆盖清单及验收版本。

## 12. 注册案例并生成运行配置

**本节生成文件：**

| 输出路径 | 必需性 | 用途 |
|---|---|---|
| `D\default_test.jsonl` | 本文默认子集加载必需 | 每行登记一个案例 |
| `K\abc-coding-opencode.json` | 仅开发模式选用 | 开发但不验收 |
| `K\abc-coding-full.json` | 完整流程选用 | 开发后验收 |
| `K\abc-coding-baseline.json` | 基线校准选用 | 不调用模型，验收初始代码 |

三个配置是备选入口，不是缺一不可；至少准备所需模式的配置文件即可。本文全部
生成，方便选择。文件名没有特殊魔法，实际行为由配置内容决定。

```python
index_path = dataset_root / 'default_test.jsonl'
row = {
    'case_id': case_id,
    'case_manifest': f'{case_id}/case.json',
}
index_path.write_text(
    json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8',
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
```

本代码仅针对新建单案例演练目录，不能直接覆盖已有双案例索引。正式目录的
default_test.jsonl 应保留 litemall-pr534 与 litemall-pr534_prd 两行。不能只
新建子目录而不登记索引，也不能误写成 JSON 数组。

核对模板中的 provider/model、OpenCode 可执行文件和权限策略。mock_llm 是未
使用的框架模型占位，真实模型由 OpenCode 配置选择。eval_batch_size 保持 1，
多案例串行；start_server=true 时自动启动专用服务；不启用 use_cache，保持
ignore_errors=false。未覆盖的审批仍可能使批处理记录 needs_input。

当前正式环境已有只选择 PRD 子集的索引和配置，不必为本演练重复创建。若需要
按子集选择，使用单独的 `<子集名>_test.jsonl` 及 subset_list，不能仅依赖 limit
猜测索引中哪个案例会被选择。

## 13. 静态核对生成的文件

**本节生成文件：无。** 检查文件模型、关键哈希和源码 ZIP 一致性，只打印结果；
不调用模型、不安装依赖、不运行测试。第 10～11 节可选文件缺失不阻止此检查。

```python
from evalscope.benchmarks.abc_coding.contracts import (
    CaseManifest, CaseRecord, OverlayFile, RequiredTest,
)

manifest = CaseManifest.model_validate_json(
    (case_root / 'case.json').read_bytes()
)
for line in index_path.read_text(encoding='utf-8').splitlines():
    record = CaseRecord.model_validate_json(line)
    assert record.case_id == manifest.case_id
assert sha256(task_path) == manifest.development.task_sha256

saved_sources = json.loads(
    (case_root / 'validation/source-files.json').read_bytes()
)
actual_sources = {
    path.relative_to(source_dir).as_posix(): sha256(path)
    for path in sorted(source_dir.rglob('*')) if path.is_file()
}
assert actual_sources == saved_sources
with zipfile.ZipFile(initial_zip) as archive:
    archived = {
        info.filename: hashlib.sha256(
            archive.read(info.filename)
        ).hexdigest()
        for info in archive.infolist() if not info.is_dir()
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
```

这些静态检查不能证明需求与测试覆盖完全一致，仍需人工审核和实际校准。正式使用
时不要以 Python 的 assert 代替框架内部校验；这里仅作为手工制作后的检查步骤，
不要以 `python -O` 运行它。

## 14. 可选执行基线校准与完整测评

**本节不生成新的输入文件。** 选用已有配置运行后，会在 `R\<时间戳>\` 生成
运行产物，包含 configs、logs、predictions、reviews、reports 和 artifacts。
具体文件见文末表格。它们不是打包前需要准备的输入，不要复制回源码或伪装成
新案例已验证的历史记录。

以下仍使用 Python 调用 EvalScope CLI，便于不换语言。这里用 subprocess 启动
的是 EvalScope，实际 OpenCode 任务仍通过已有 HTTP 集成提交。

```python
def run_eval(config_name: str) -> None:
    subprocess.run(
        [
            sys.executable, '-m', 'evalscope.cli.cli', 'eval',
            '--task-config', str(config_root / config_name),
        ],
        cwd=evalscope_repo, check=True,
    )


run_eval('abc-coding-baseline.json')
```

这会安装项目依赖、运行类型与浏览器测试，不调用模型。预期为 6 项 F2P 失败、
13 项 P2P 通过，类型检查通过；基线 resolved=0 是预期，不是模型成绩。当前包
是否达到这一结果必须查看本次报告，不能仅依据历史结论。

环境与基线确认后，再选择执行下一代码块；它会实际调用配置中的模型：

```python
run_eval('abc-coding-full.json')
```

仅开发时改用 abc-coding-opencode.json，不要把“会话正常结束”等同于“验收
通过”。本机需具备 Node/npm、Chrome 等工具，测试端口不得被占用；无需提前
启动本案例的 Vue 服务，Playwright webServer 负责启动和就绪检查。

## 15. 可选生成历史候选重验配置

**本节生成输入文件：`K\abc-coding-verify.json`，仅重验时需要。** 需先有
匹配本案例身份的真实候选。最后的执行语句另生成 `R\<新时间戳>\` 下的验收
运行产物，不产生新的智能体开发结果，也不调用 OpenCode。

```python
candidate_dir = Path(input('Candidate attempt directory: ').strip())
for name in ('execution.json', 'candidate.json', 'candidate.zip'):
    if not (candidate_dir / name).is_file():
        raise FileNotFoundError(candidate_dir / name)

execution = json.loads((candidate_dir / 'execution.json').read_bytes())
if execution['case_id'] != case_id:
    raise ValueError('Candidate belongs to a different case.')
if execution['task_sha256'] != task_hash:
    raise ValueError('Candidate task differs from this package.')

baseline_config = config_root / 'abc-coding-baseline.json'
verify_config = json.loads(baseline_config.read_bytes())
verify_config['model'] = execution['model_id'] + '-opencode'
extra = verify_config['dataset_args']['abc_coding']['extra_params']
extra['coding'] = {
    'mode': 'verify_only',
    'candidates': {case_id: str(candidate_dir)},
}
write_json(config_root / 'abc-coding-verify.json', verify_config)
```

按需执行，生成新验收记录：

```python
run_eval('abc-coding-verify.json')
```

多案例重验时，索引中的每个待验案例都需有对应候选映射，不能把简版案例候选
作为 PRD 案例候选。执行器还会核对案例版本、任务哈希与源清单文件哈希；即使
源码内容相同，重新生成源清单时排序、换行等字节差异仍可能导致身份不同。

## 16. 查看报告与正式发布

**本节生成文件：无新的案例输入文件。** 下方命令只启动服务读取既有产物。
如果另行构建 Web 前端，会生成 `E:\code\evalscope\evalscope\web\dist\**\*`，
这是可选 UI 构建产物，不是案例包或评分必需文件。npm 安装还会生成该目录下的
node_modules 等工具产物，本说明不把依赖文件列为案例输入。

```python
subprocess.run(
    [
        sys.executable, '-m', 'evalscope.cli.cli', 'service',
        '--host', '127.0.0.1', '--outputs', str(runs_root),
    ],
    cwd=evalscope_repo, check=True,
)
```

浏览器访问 `http://localhost:9000/reports`。若没有前端 dist，需要按仓库前端
构建流程安装依赖并构建，再重启服务；也可直接打开运行的 reports/report.html。
UI 中 NUM 是贡献该指标的案例样本数，不是单元或 E2E 测试条数。逐条测试结果
查看 artifacts/verification 下的 verification.json。

发布到正式目录时，先备份已有同名包；把审核好的案例放入
`E:\custom_benchmark\evalscope_cases`，更新索引与配置路径。保留旧简版案例，
不要把本文单行索引覆盖现有双案例索引。不要把 S 临时文件或 runs 放入案例包。
旧文档以及现有历史结果无需为本版教程而覆盖。

## 17. 全部生成文件汇总

**本节生成文件：无。** 下表为前文输出的完整分类清单。路径记号见第 1 节；
`**\*` 表示由 Git、测试工具或框架决定名称的文件集合，不是一个字面文件名。
本例验收文件逐项列出，源码与依赖等大量文件按生成目录列出。

| 文件或文件集合路径 | 生成节 | 必需性 | 功能简介 |
|---|---|---|---|
| `C\source\initial.zip` | 4 | 基线校准必需 | 无 Git 历史的固定源码归档 |
| `C\source\initial\**\*` | 4 | 开发必需 | 同一归档的源码展开文件 |
| `C\task.md` | 5 | 必需 | 完整 PRD 的字节副本 |
| `S\trusted-files.zip` | 6 | 临时 | 仅导出白名单验收资料 |
| `S\trusted\litemall-admin\**\*` | 6 | 临时 | 16 个验收文件的上游副本 |
| `C\verifier\tests\README.md` | 6 | 本清单引用；内容可选 | 上游测试说明 |
| `C\verifier\tests\e2e\fixtures.ts` | 6 | 验收必需 | 浏览器与 API 模拟辅助代码 |
| `C\verifier\tests\e2e\goods-list.spec.ts` | 6 | 验收必需 | 10 项 E2E；含两处断言修正 |
| `C\verifier\tests\unit\goods-list.spec.ts` | 6 | 验收必需 | 9 项单元测试 |
| `C\verifier\tests\tsconfig.json` | 6 | 验收必需 | 测试类型检查配置 |
| `C\verifier\tests\vue.d.ts` | 6 | 验收必需 | Vue 测试类型声明 |
| `C\verifier\config\package.json` | 6 | 验收必需 | 依赖声明与测试脚本 |
| `C\verifier\config\package-lock.json` | 6 | 验收必需 | 锁定 npm 依赖 |
| `C\verifier\config\jest.config.js` | 6 | 验收必需 | 单元测试发现与执行配置 |
| `C\verifier\config\babel.config.js` | 6 | 验收必需 | 测试编译转换配置 |
| `C\verifier\config\playwright.config.ts` | 6 | 验收必需 | 浏览器、报告及 webServer 配置 |
| `C\verifier\config\vue.config.js` | 6 | 验收必需 | 前端构建和测试启动配置 |
| `C\verifier\config\postcss.config.js` | 6 | 验收必需 | 样式处理配置 |
| `C\verifier\config\jsconfig.json` | 6 | 验收必需 | JavaScript 项目配置 |
| `C\verifier\config\.env.development` | 6 | 验收必需 | 前端开发环境参数 |
| `C\verifier\config\scripts\serve-e2e.js` | 6 | 验收必需 | 前端测试服务器启动脚本 |
| `C\validation\source-files.json` | 7 | 开发必需 | 全量源码文件哈希 |
| `C\verifier\overlay-manifest.json` | 7 | 验收必需 | 可信文件路径映射和哈希 |
| `C\verifier\test-inventory.json` | 8 | 验收必需 | 19 个必需 ID 和评分分组，无 title |
| `C\case.json` | 9 | 必需 | 案例身份、任务哈希、执行配方 |
| `C\README.md` | 10 | 可选 | 人工阅读入口 |
| `C\ENVIRONMENT.md` | 10 | 可选 | 环境准备和测试边界 |
| `C\SCORING.md` | 10 | 可选 | 人可读评分说明 |
| `C\validation\provenance.json` | 10 | 可选 | 来源与本地变更记录 |
| `C\validation\checksums.json` | 11 | 可选 | 整包文件哈希，不包含自身 |
| `D\default_test.jsonl` | 12 | 本文默认加载必需 | 案例索引 |
| `K\abc-coding-opencode.json` | 12 | 对应模式选用 | 仅开发入口 |
| `K\abc-coding-full.json` | 12 | 对应模式选用 | 开发与验收入口 |
| `K\abc-coding-baseline.json` | 12 | 对应模式选用 | 起始代码校准入口 |
| `K\abc-coding-verify.json` | 15 | 重验选用 | 已有候选路径映射 |
| `R\<时间戳>\configs\**\*` | 14、15 | 运行产物 | 运行配置快照 |
| `R\<时间戳>\logs\**\*` | 14、15 | 运行产物 | 框架日志 |
| `R\<时间戳>\predictions\**\*` | 14、15 | 运行产物 | 标准预测记录 |
| `R\<时间戳>\reviews\**\*` | 14、15 | 运行产物 | 评分、元数据和轨迹 |
| `R\<时间戳>\reports\**\*` | 14、15 | 运行产物 | JSON 与 report.html 等报告 |
| `R\<时间戳>\artifacts\abc_coding\**\*` | 14、15 | 运行产物 | 开发工作区、会话、候选及批次摘要 |
| `R\<时间戳>\artifacts\verification\**\*` | 14、15 | 运行产物 | 验收副本、配方、清单、日志及报告 |
| `E:\code\evalscope\evalscope\web\dist\**\*` | 16（另行构建） | 可选 UI 产物 | 浏览器页面，不属于案例输入 |
| `E:\code\evalscope\evalscope\web\node_modules\**\*` | 16（另行安装） | 可选构建依赖产物 | 前端工具依赖，不属于案例输入 |
