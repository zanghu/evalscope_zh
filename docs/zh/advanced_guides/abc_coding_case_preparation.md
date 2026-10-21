# 从 Git 分支手工整理 ABC Coding 本地案例包

本文以 litemall PR #534 为例，说明如何把 Git 分支中的起始代码、可信测试和已有需求文件，整理成当前 `abc_coding` 适配器能够使用的本地输入。适用于本项目当前实现，不是 EvalScope 所有基准的通用官方数据格式。

操作以 Windows PowerShell 为主。命令块应在同一个 PowerShell 会话中按顺序执行；它们是逐步的文件整理命令，不需要再开发新的运行框架。本文不要求切换或修改 litemall 仓库的工作分支，也不修改其中的源代码。

## 1. 输入资料与目标

| 输入 | 本案例取值 | 用途 |
|---|---|---|
| 本地 Git 仓库 | `E:\code\litemall` | 导出已提交文件 |
| 起始分支 | `benchmark_pr_534` | 尚未实现批量删除功能的任务输入 |
| 测试分支 | `benchmark_pr_534_finish_opencode_20260916_test` | 提取测试与运行配置；此分支同时含答案，不能整体作为初始代码 |
| 需求原文件 | `E:\2024年10月01日codeABC任务\2026年03月16日部门研究课题企业级编程智能体\litemall案例抽取实验\PR_534生成PRD\part1_prompt_vision2web.txt` | 复制成 `task.md` |
| EvalScope 工作仓库 | `E:\code\evalscope` | 已有适配器、运行入口和配置示例 |

统一用“需求文件”和“起始代码”称呼输入，避免历史交流中 part1/part2 曾经对调造成误解。对应关系为：需求文件是 part1，起始代码是 part2。

截至 2026-09-20，本机两分支的提交为：

- 起始提交：`e94d1b3d66f9d6641326cf4469d9ef82c12e79ff`。
- 测试提交：`48d92b49b976c73d70d7add76bf0c0bd170b00d2`。

分支名是可移动的，发布案例时应记录解析出的完整 SHA。若以后 SHA 变化，不应直接假定仍是本案例同一版本。错误分支 `benchmark_pr_534_init` 已包含目标功能，不能作为本案例起始输入。

最终主要形成以下结构：

```text
custom_benchmark/
  configs/
    abc-coding-opencode.json       # 仅开发
    abc-coding-full.json           # 开发 + 验收
    abc-coding-baseline.json       # 起始代码校准
    abc-coding-verify.json         # 对指定历史候选验收，产生候选后再填写
  evalscope_cases/
    default_test.jsonl             # 案例索引，一行一个案例
    litemall-pr534/
      case.json                   # 案例描述与验收执行配方
      task.md                     # 需求
      README.md                   # 资料来源和使用说明
      ENVIRONMENT.md              # 环境说明
      SCORING.md                  # 评分规则
      source/
        initial.zip               # 原始代码导出；用于基线校准
        initial/                  # 同一 ZIP 展开；用于准备开发目录
      verifier/
        tests/                    # 可信测试，不放业务实现
        config/                   # 可信依赖、构建和测试配置
        overlay-manifest.json     # 包内文件到验收工作区的映射及哈希
        test-inventory.json       # 必须出现的测试 ID 及分组
      reference/                  # 空占位，不要求参考实现
      validation/
        source-files.json         # 起始目录每个文件的 SHA256
        provenance.json           # 来源与人工调整记录
        checksums.json            # 整个案例包的检查清单
  runs/                           # 执行时生成，不是输入资料
```

`case.json`、索引、源码、任务、源文件哈希以及验收配方引用的文件是运行所需内容。README、环境说明、来源记录和包级校验清单便于人工审核与维护。现有包里的历史 `validation/*.json` 是已有运行的证据，不应复制到新包中冒充新验证。现有 `verifier/prepare.ps1` 是可选人工调试工具，适配器不依赖它。

## 2. 在新目录中演练，避免覆盖现有案例

本机已有正式案例，以下命令默认写入新建的演练根目录。成功后可直接用演练配置运行；需要正式发布时再人工备份、迁移并更新配置路径。不要把命令中的根目录改为现有正式目录后直接覆盖。

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'E:\code\litemall'
$evalscopeRepo = 'E:\code\evalscope'
$bundleRoot = 'E:\custom_benchmark_manual'
$datasetRoot = Join-Path $bundleRoot 'evalscope_cases'
$configRoot = Join-Path $bundleRoot 'configs'
$caseRoot = Join-Path $datasetRoot 'litemall-pr534'
$stageRoot = Join-Path $bundleRoot '_staging'
$runsRoot = Join-Path $bundleRoot 'runs'

if (Test-Path -LiteralPath $bundleRoot) {
    throw 'Choose a new bundleRoot; do not overwrite an existing package.'
}
foreach ($dir in @($configRoot, $stageRoot, $runsRoot, $caseRoot,
    "$caseRoot\source", "$caseRoot\verifier\config", "$caseRoot\reference", "$caseRoot\validation")) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

# Write JSON as UTF-8 without BOM, including on Windows PowerShell 5.1.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-JsonFile($Path, $Value) {
    $json = ConvertTo-Json -InputObject $Value -Depth 30
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $utf8NoBom)
}
function Get-Sha256($Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
```

JSON 文件应保存为 UTF-8 无 BOM。不要使用 Windows PowerShell 5.1 的默认 `>` 去生成源码、JSON 或 ZIP；文本重编码可能改变内容。Git ZIP 使用 `--output`，文本使用上述写入方法。

## 3. 固定提交，并人工确认起始状态

```powershell
$sourceSha = (git -C $repo rev-parse 'benchmark_pr_534^{commit}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve initial branch.' }
$testsSha = (git -C $repo rev-parse 'benchmark_pr_534_finish_opencode_20260916_test^{commit}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve tests branch.' }
$sourceSha
$testsSha

git -C $repo log -1 --oneline $sourceSha
git -C $repo diff --stat $sourceSha $testsSha
git -C $repo diff $sourceSha $testsSha -- litemall-admin/src/views/goods/list.vue
```

人工查看差异，确认起始版本没有任务要求的批量删除实现，同时保留原有商品列表和单条删除等行为。不要只凭分支名称判定正确性；后面的基线校准用于进一步验证。

这些命令读取本地 Git 对象，不自动 fetch，不包含尚未提交的工作区修改。若需要更新远端分支，先明确采用哪个提交再打包。

## 4. 导出起始代码，不携带答案历史

```powershell
$initialZip = Join-Path $caseRoot 'source\initial.zip'
git -C $repo archive --format=zip "--output=$initialZip" $sourceSha
if ($LASTEXITCODE -ne 0) { throw 'Initial archive failed.' }
Expand-Archive -LiteralPath $initialZip -DestinationPath "$caseRoot\source\initial"

if (Test-Path -LiteralPath "$caseRoot\source\initial\.git") {
    throw 'Initial source must not contain Git metadata.'
}
```

ZIP 的根层应直接出现 `litemall-admin`、后端模块等项目内容，不能额外套一层仓库文件夹。`git archive` 不导出 `.git`，因而不会把分支和答案提交历史送入开发目录。执行器会在每次开发目录中创建一个新的 Git 基线，无需手动初始化案例包的 `source/initial`。

不要向这里复制测试分支的文件，也不要在这里运行安装或构建。保持 `initial.zip` 与 `initial/` 内容一致；若要改变起始代码，应重新确定版本、导出并重算清单。

本仓库的导出方式已验证适用。其他仓库若使用 Git LFS、子模块或 `export-ignore`，必须额外确认导出的是实际完整源码，不能照搬“ZIP 一定包含所有文件”的假设。

## 5. 复制需求文件

```powershell
$promptFile = 'E:\2024年10月01日codeABC任务\2026年03月16日部门研究课题企业级编程智能体\litemall案例抽取实验\PR_534生成PRD\part1_prompt_vision2web.txt'
Copy-Item -LiteralPath $promptFile -Destination "$caseRoot\task.md"
```

本案例原文件可直接复制，不因为扩展名由 txt 改成 md 而重写内容。打开文件检查中文编码；适配器按 UTF-8 读取。若来源文件不是 UTF-8，应先明确转换，再计算任务哈希。

检查需求是否独立完整，是否夹带答案补丁、指向测试分支的提示或依赖无法访问的附件。现阶段不用补齐未覆盖需求的测试，但应记录覆盖范围。需求修改后必须更新任务哈希，并重新考虑案例版本，不能继续将旧候选当作完全相同任务。

## 6. 从测试分支只提取可信验收材料

不能复制整个测试分支，因为它包含此前 OpenCode 完成的业务实现。本案例允许提取的文件如下：

| Git 路径 | 案例包内位置 |
|---|---|
| `litemall-admin/tests/` | `verifier/tests/` |
| `litemall-admin/package.json` | `verifier/config/package.json` |
| `litemall-admin/package-lock.json` | `verifier/config/package-lock.json` |
| `litemall-admin/jest.config.js` | `verifier/config/jest.config.js` |
| `litemall-admin/babel.config.js` | `verifier/config/babel.config.js` |
| `litemall-admin/playwright.config.ts` | `verifier/config/playwright.config.ts` |
| `litemall-admin/vue.config.js` | `verifier/config/vue.config.js` |
| `litemall-admin/postcss.config.js` | `verifier/config/postcss.config.js` |
| `litemall-admin/jsconfig.json` | `verifier/config/jsconfig.json` |
| `litemall-admin/.env.development` | `verifier/config/.env.development` |
| `litemall-admin/scripts/serve-e2e.js` | `verifier/config/scripts/serve-e2e.js` |

```powershell
$configFiles = @(
    'package.json', 'package-lock.json', 'jest.config.js', 'babel.config.js',
    'playwright.config.ts', 'vue.config.js', 'postcss.config.js',
    'jsconfig.json', '.env.development', 'scripts/serve-e2e.js'
)
$gitPaths = @('litemall-admin/tests') + @($configFiles | ForEach-Object { "litemall-admin/$_" })
$verifierZip = Join-Path $stageRoot 'trusted-files.zip'
git -C $repo archive --format=zip "--output=$verifierZip" $testsSha -- @gitPaths
if ($LASTEXITCODE -ne 0) { throw 'Trusted files export failed.' }
Expand-Archive -LiteralPath $verifierZip -DestinationPath "$stageRoot\trusted"
$trustedAdmin = Join-Path $stageRoot 'trusted\litemall-admin'
Copy-Item -LiteralPath "$trustedAdmin\tests" -Destination "$caseRoot\verifier\tests" -Recurse
foreach ($relative in $configFiles) {
    $dest = Join-Path "$caseRoot\verifier\config" $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $trustedAdmin $relative) -Destination $dest
}
```

特别不要提取 `src/views/goods/list.vue`、`src/locales/en.js` 和 `src/locales/zh-Hans.js` 等业务修改。提取配置文件并不意味着无须审核：检查 package scripts、Vue/Babel 配置和启动脚本，确认它们是测试所需配置，没有内嵌或替换目标业务实现。本案例这些文件按上述范围提取。

测试目录共 6 个文件：README、`e2e/fixtures.ts`、`e2e/goods-list.spec.ts`、`unit/goods-list.spec.ts`、`tsconfig.json`、`vue.d.ts`。加上 10 个配置文件，共有 16 个可信覆盖文件。

### 必须重放已确认的两处断言修正

Git 测试提交仍含旧断言。打开新包的 `verifier/tests/e2e/goods-list.spec.ts`，仅在 `F2P-E02`、`F2P-E03` 中，把：

```typescript
await expect(page.getByText('删除成功', { exact: true }).first()).toBeVisible()
```

改为：

```typescript
await expect(page.locator('.el-notification:has(.el-icon-success)').first()).toBeVisible()
```

保留删除对象、刷新、未选商品等所有行为断言。不要全文件替换；P2P 中单条删除的同名断言保持原样。此修正允许“批量删除成功”等有效反馈，避免把文案差异判为功能失败。保存后再生成哈希，并在来源记录中标明这两个本地修改。

可与暂存的原文件比较，预期只有两行断言变化（编辑器若改变编码或换行，也应识别出来）：

```powershell
git diff --no-index -- "$trustedAdmin\tests\e2e\goods-list.spec.ts" "$caseRoot\verifier\tests\e2e\goods-list.spec.ts"
# Exit code 1 means differences were found; it is expected here.
```

## 7. 生成两个不同用途的文件清单

### 7.1 起始源码哈希

执行器用它确认开发输入文件没有被添加、删除或改写。相对路径以 `source/initial` 为根，不能带此前缀。

```powershell
$sourceDir = [IO.Path]::GetFullPath("$caseRoot\source\initial").TrimEnd('\')
$sourceHashes = [ordered]@{}
Get-ChildItem -LiteralPath $sourceDir -Recurse -Force -File | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($sourceDir.Length + 1).Replace('\', '/')
    $sourceHashes[$relative] = Get-Sha256 $_.FullName
}
Write-JsonFile "$caseRoot\validation\source-files.json" $sourceHashes
$taskHash = Get-Sha256 "$caseRoot\task.md"
```

### 7.2 可信覆盖清单

清单表示“验收时将这个包内文件复制到候选副本的哪个位置”，不是要求候选业务文件必须与测试分支一致。

```powershell
$overlay = @()
foreach ($section in @('tests', 'config')) {
    $base = [IO.Path]::GetFullPath("$caseRoot\verifier\$section").TrimEnd('\')
    foreach ($file in (Get-ChildItem -LiteralPath $base -Recurse -Force -File | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($base.Length + 1).Replace('\', '/')
        $target = if ($section -eq 'tests') { "litemall-admin/tests/$relative" } else { "litemall-admin/$relative" }
        $entry = [ordered]@{
            package_path = "verifier/$section/$relative"
            target_path = $target
            sha256 = Get-Sha256 $file.FullName
            source_commit = $testsSha
            source_path = $target
        }
        if ($entry.package_path -eq 'verifier/tests/e2e/goods-list.spec.ts') {
            $entry['upstream_sha256'] = Get-Sha256 "$trustedAdmin\tests\e2e\goods-list.spec.ts"
            $entry['local_modification'] = 'F2P-E02/E03 check success notification type, not exact wording.'
        }
        $overlay += $entry
    }
}
if ($overlay.Count -ne 16) { throw 'Expected 16 trusted files; review extraction.' }
Write-JsonFile "$caseRoot\verifier\overlay-manifest.json" $overlay
```

哈希必须针对最终字节计算，不能先生成哈希再修改测试。记录的 `source_commit` 代表来源，`local_modification` 说明它已不是来源提交的逐字副本。

## 8. 编制必须执行的测试清单

`suite` 对应验收步骤名，`id` 必须出现在测试报告的名称中。不能只统计“测试程序退出码为 0”，否则漏跑测试也可能被误认为通过。

| suite | F2P | P2P | 合计 |
|---|---|---|---|
| unit | F2P-U01～U02 | P2P-U01～U07 | 9 |
| e2e | F2P-E01～E04 | P2P-E01～E06 | 10 |
| 总计 | 6 | 13 | 19 |

下面按已审核的 ID 范围手工建表，不从某次运行结果反向生成清单：

```powershell
$inventory = @()
foreach ($groupSpec in @(
    @{ suite = 'unit'; group = 'F2P'; prefix = 'F2P-U'; max_id = 2 },
    @{ suite = 'unit'; group = 'P2P'; prefix = 'P2P-U'; max_id = 7 },
    @{ suite = 'e2e'; group = 'F2P'; prefix = 'F2P-E'; max_id = 4 },
    @{ suite = 'e2e'; group = 'P2P'; prefix = 'P2P-E'; max_id = 6 }
)) {
    foreach ($number in 1..$groupSpec.max_id) {
        $inventory += [ordered]@{
            id = $groupSpec.prefix + $number.ToString('00')
            suite = $groupSpec.suite
            group = $groupSpec.group
            required = $true
        }
    }
}
Write-JsonFile "$caseRoot\verifier\test-inventory.json" $inventory
```

当前协议允许附加 `title` 便于阅读，但实际匹配依据是 suite 和 ID。其他项目需要逐项审核测试含义，不能根据文件名自动推断 F2P/P2P。类型检查单列为 gate，不计入 19 条功能测试。

## 9. 写入案例描述及验收配方

下面生成当前适配器可用的精简 `case.json`，无需复制历史包中所有说明字段：

```powershell
$case = [ordered]@{
    schema_version = '0.1.0'
    case_id = 'litemall-pr534'
    case_version = '0.3.0'
    evaluation_version = '1.2.0'
    title = 'litemall 管理后台商品批量删除'
    task_file = 'task.md'
    source_archive = 'source/initial.zip'
    source_branch = 'benchmark_pr_534'
    source_commit = $sourceSha
    tests_commit = $testsSha
    development = [ordered]@{
        source_directory = 'source/initial'
        source_checksums = 'validation/source-files.json'
        working_directory = '.'
        task_sha256 = $taskHash
    }
    verification = [ordered]@{
        version = '1.1.0'
        working_directory = 'litemall-admin'
        overlay_manifest = 'verifier/overlay-manifest.json'
        test_inventory = 'verifier/test-inventory.json'
        environment = @{ CI = 'true'; NODE_OPTIONS = '--openssl-legacy-provider'; PLAYWRIGHT_CHANNEL = 'chrome' }
        ports = @(9528)
        steps = @(
            @{ name = 'install'; kind = 'setup'; command = @('npm','ci','--no-audit','--no-fund'); timeout = 1200 },
            @{ name = 'types'; kind = 'gate'; command = @('npm','run','test:types'); timeout = 180 },
            @{ name = 'unit'; kind = 'tests'; command = @('npm','run','test:unit','--','--json','--outputFile=unit-results.json'); timeout = 300; report_format = 'jest'; report_path = 'unit-results.json' },
            @{ name = 'e2e'; kind = 'tests'; command = @('npm','run','test:e2e'); timeout = 900; report_format = 'junit'; report_path = 'test-results/e2e.xml' }
        )
    }
    reference = @{ directory = 'reference'; available = $false }
}
Write-JsonFile "$caseRoot\case.json" $case
```

这些版本值对应当前 litemall 案例；不同案例请自行从明确的初始版本开始。起始代码或需求改变应更新案例版本，验收语义改变应更新验收/评价版本并重新校准。不要只修改声明版本而忽略实际文件内容。

路径含义：

- `development.working_directory = '.'`：智能体从完整仓库根目录工作。
- `verification.working_directory = 'litemall-admin'`：依赖、类型检查和测试命令在前端目录执行。
- `package_path`、`task_file` 等资源路径相对案例根目录；覆盖清单的 `target_path` 相对候选仓库根目录；报告路径相对验收工作目录。
- 当前运行读取的是 `verification.steps`。历史包的 `execution.commands` 是说明性字段，不能只改它来改变验收行为。

所有命令使用参数数组，不写 `npm ci && npm test` 这样的 shell 拼接字符串。不同技术栈通过替换命令、工作目录、环境和报告格式适配；本实现目前内置 Jest JSON、JUnit XML 两种解析器。

## 10. 补齐人可读说明与来源记录

手工创建三个 UTF-8 文档，至少覆盖下列内容：

| 文件 | 应写内容 |
|---|---|
| README.md | 案例 ID、需求目的、两个固定提交、目录用途、运行入口、参考实现为空 |
| ENVIRONMENT.md | Windows；已验证 Node 22.14.0/npm 10.9.2；Git、Python/EvalScope、OpenCode 与 Chrome 的准备；端口与网络条件 |
| SCORING.md | 19 项必需测试和类型 gate；全部通过 resolved=1；明确功能失败为 0；无法解释的验收异常单列；F2P/P2P 分组通过率；验收版本 1.1.0 的两项断言修正 |

本案例的环境说明应特别写清：

- 当前验收只验证管理后台前端，API 和登录等由 fixtures 模拟，不需要真实 Java 后端、MySQL 或测试账号；不代表覆盖了真实前后端集成。
- Playwright 使用本机 Chrome，端口为 9528；它的 `webServer` 负责启动 Vue 测试服务器、等待就绪和结束清理。无需提前手动部署服务。
- 依赖以可信 package.json 和 package-lock.json 为准，验收在新目录执行 `npm ci`。这两个文件覆盖候选副本中的对应文件，所以首版不适合要求自由新增依赖而验收配置又未更新的任务。
- OpenCode 服务端口是 41960，报告 UI 默认端口是 9000，与前端测试端口不同。
- 工具应预装。锁文件镜像必须可达；凭据保存在 OpenCode 配置或环境中，不写入案例包。
- 开发工作区不主动注入可信验收测试；本地文件目录分离并非操作系统沙箱。

来源记录可用以下命令生成：

```powershell
Write-JsonFile "$caseRoot\validation\provenance.json" ([ordered]@{
    packaged_on = (Get-Date -Format 'yyyy-MM-dd')
    local_repository = $repo
    source_branch = 'benchmark_pr_534'
    source_commit = $sourceSha
    tests_branch = 'benchmark_pr_534_finish_opencode_20260916_test'
    tests_commit = $testsSha
    prompt_source = $promptFile
    export_method = 'git archive --format=zip <fixed-commit>'
    test_assertions_modified = $true
    modified_tests = @('F2P-E02','F2P-E03')
    modification = 'Check visible success notification instead of exact success wording.'
    tests_added = $false
    reference_included = $false
    validation_status = 'not_run_for_this_package'
})
```

不要把 `not_run` 写成 `passed`。重新运行校准或候选验收后，再单独保存实际运行路径、版本和结果。

## 11. 生成包级校验清单

先保存前面所有文件，然后执行：

```powershell
$packageBase = [IO.Path]::GetFullPath($caseRoot).TrimEnd('\')
$checksumPath = Join-Path $caseRoot 'validation\checksums.json'
$packageHashes = [ordered]@{}
Get-ChildItem -LiteralPath $caseRoot -Recurse -Force -File | Sort-Object FullName | ForEach-Object {
    if ($_.FullName -ne $checksumPath) {
        $relative = $_.FullName.Substring($packageBase.Length + 1).Replace('\', '/')
        $packageHashes[$relative] = Get-Sha256 $_.FullName
    }
}
Write-JsonFile $checksumPath $packageHashes
```

清单不包含自身，否则会自引用。当前适配器运行时使用源清单、任务哈希及覆盖清单进行关键校验，并非自动逐项读取这个包级清单。新增验证记录或修订说明文件后，可重新执行本节更新包级清单；改变可信测试时必须同时更新覆盖清单和版本。

## 12. 注册案例，并准备批量运行配置

### 12.1 案例索引

```powershell
$indexRow = '{"case_id":"litemall-pr534","case_manifest":"litemall-pr534/case.json"}'
[IO.File]::WriteAllText((Join-Path $datasetRoot 'default_test.jsonl'), $indexRow + "`n", $utf8NoBom)
```

以上覆盖写入只适用于本教程新建的单案例目录。已有多案例索引应编辑追加并检查 ID 唯一性，不能运行这段覆盖已有列表。JSONL 不是 JSON 数组，不加外层方括号，不在行末加逗号。

未来增加案例时，在 `evalscope_cases` 下创建另一个案例目录，并向索引加一行即可。当前实现不会仅因为发现子目录就自动执行它；以索引为准。

### 12.2 复用仓库内现成的配置模板

无需逐个手写 OpenCode 权限与连接配置：

```powershell
$templates = @{
    'opencode.json' = 'abc-coding-opencode.json'
    'full.json' = 'abc-coding-full.json'
    'baseline.json' = 'abc-coding-baseline.json'
}
foreach ($templateName in $templates.Keys) {
    $templatePath = Join-Path "$evalscopeRepo\examples\abc_coding" $templateName
    $config = Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $config.dataset_args.abc_coding.local_path = $datasetRoot.Replace('\', '/')
    $config.work_dir = $runsRoot.Replace('\', '/')
    Write-JsonFile (Join-Path $configRoot $templates[$templateName]) $config
}
```

打开生成配置，核对：

- `datasets` 为 `["abc_coding"]`，`local_path` 指向数据集根目录，而不是单个案例目录。
- `eval_batch_size = 1`：一次运行可以加载多案例，目前按案例串行执行。
- `eval_type = "mock_llm"` 只是未使用的框架模型占位，OpenCode 实际使用 `provider_id = "deepseek"`、`model_id = "deepseek-v4-flash"`。
- `start_server = true` 自动启动本机 OpenCode 服务；`executable` 必须能定位本机 OpenCode。不要预先占用对应端口。
- `ignore_errors = false`；当前适配器不支持 `use_cache` 恢复。
- 模板权限未覆盖的工具仍可能要求审批；本批处理遇到待审批状态会停止该会话并记录状态，不会自动批准。现有默认权限并不保证任意案例都无需人工处理。

配置描述“本批次怎么运行”，案例索引描述“有哪些案例”，各 case.json 描述“每个案例是什么、如何验收”。因此不需要为每个新案例再建一份完整批量配置。

## 13. 完成前检查与基线校准

手工检查：

1. `source/initial` 中没有 `.git`、新装 node_modules 或后来注入的验收文件；不要因原提交本来存在某个目录而盲目删除它。
2. ZIP 展开层级正确，与 `initial/` 内容一致。
3. 需求可读，分支和 SHA 正确；覆盖文件只有审核过的 16 个，没有业务 src。
4. 两处提示断言已修正，覆盖清单哈希反映最终文件；19 个 ID 与测试定义一致。
5. JSON/JSONL 为 UTF-8 无 BOM，路径和步骤名匹配；配置指向本次新目录。

可在 EvalScope Python 环境中验证数据模型，不调用 OpenCode：

```powershell
Set-Location $evalscopeRepo
@'
import json
import sys
from pathlib import Path
from evalscope.benchmarks.abc_coding.contracts import CaseManifest, OverlayFile, RequiredTest

p = Path(sys.argv[1])
m = CaseManifest.model_validate_json((p / 'case.json').read_bytes())
for entry in json.loads((p / m.verification.overlay_manifest).read_bytes()):
    OverlayFile.model_validate(entry)
for entry in json.loads((p / m.verification.test_inventory).read_bytes()):
    RequiredTest.model_validate(entry)
print('Case schema OK')
'@ | python - $caseRoot
if ($LASTEXITCODE -ne 0) { throw 'Case schema validation failed.' }
```

然后执行起始代码校准：

```powershell
python -m evalscope.cli.cli eval --task-config "$configRoot\abc-coding-baseline.json"
```

此命令不调用模型，但会创建独立运行目录、安装依赖、启动浏览器和前端测试服务器。预期类型检查通过、6 项 F2P 失败、13 项 P2P 通过。`resolved=0` 是这一基线的预期结果，不是模型成绩。

上述数量是案例设计预期及历史校准结果；新打包后的实际结果必须查看报告确认，不能直接写成已验证。若 F2P 全通过，优先怀疑起始代码含答案；P2P 失败需检查测试环境和基线；缺失报告、依赖失败或超时不能据此判断案例功能。

## 14. 执行开发与验收，或单独重验

确认环境与基线后，可完整运行：

```powershell
python -m evalscope.cli.cli eval --task-config "$configRoot\abc-coding-full.json"
```

仅开发则使用 `abc-coding-opencode.json`。成功运行后，找到：

```text
runs/<时间戳>/artifacts/abc_coding/litemall-pr534/<attempt_id>/
  execution.json
  candidate.json
  candidate.zip
  candidate.patch
  session.json
  workspace/
```

需要单独验收时，用实际 attempt 路径生成配置，而不是照抄模板中的旧运行路径：

```powershell
$candidateDir = Read-Host 'Paste the actual attempt directory containing execution.json and candidate.zip'
foreach ($name in @('execution.json','candidate.json','candidate.zip')) {
    if (-not (Test-Path -LiteralPath (Join-Path $candidateDir $name))) {
        throw "Missing candidate file: $name"
    }
}
$verifyConfig = Get-Content -LiteralPath "$configRoot\abc-coding-baseline.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$verifyConfig.model = 'deepseek-v4-flash-opencode'
$verifyConfig.dataset_args.abc_coding.extra_params.coding = [ordered]@{
    mode = 'verify_only'
    candidates = @{ 'litemall-pr534' = $candidateDir }
}
Write-JsonFile "$configRoot\abc-coding-verify.json" $verifyConfig
python -m evalscope.cli.cli eval --task-config "$configRoot\abc-coding-verify.json"
```

多案例重验时，为索引中每个待验案例填写对应候选映射，或使用只包含目标案例的独立数据集索引。重验读取既有候选并创建新的验收目录，不重新调用 OpenCode。

输入身份必须匹配：手工重建后，即使 SHA 字典含义一样，`source-files.json` 的排序或换行不同也可能造成文件哈希不同；执行器按完整源清单文件哈希判断。不要认为新建包能直接重验旧包产生的候选。重验旧候选优先使用原包的原始源清单和任务文件，不能通过改写候选元数据绕过身份检查。

## 15. 查看结果与发布正式案例

```powershell
python -m evalscope.cli.cli service --host 127.0.0.1 --outputs "$runsRoot"
```

浏览器访问 `http://localhost:9000/reports`。若前端尚未构建，在另一个终端进入 `E:\code\evalscope\evalscope\web`，运行 `npm.cmd ci`、`npm.cmd run build`，每步检查退出码，成功后重启 service。也可直接打开新运行的 `reports/report.html`。模型结束状态、验收状态、解决率是不同信息，分别查看 execution、verification 和报告。

演练包满足要求后，可保留该根目录作为新数据集，也可通过资源管理器发布到正式目录：

1. 停止使用目标包的新任务，先把已有同名案例与配置备份到案例索引之外。
2. 将审核通过的新案例目录复制到正式 `E:\custom_benchmark\evalscope_cases`；不要合并覆盖而遗留旧文件。
3. 保留正式索引中的其他案例，只新增或更新对应条目。
4. 将运行配置的 `local_path`、`work_dir` 改为正式数据集及输出路径；历史候选路径按实际填写。
5. 保留校准记录、原始 SHA、版本与修改说明；变更后的正式包重新检查。

不要把 `_staging`、运行目录或测试分支的完整仓库放入案例包。`reference` 空目录可在本地保留；如需通过 Git 保存空占位，应自行决定是否增加占位文件。

## 16. 换成其他项目时需重新判断的部分

可复用目录结构、JSONL 索引、数据协议、执行与报告流程；不能原样复用 litemall 的验收配方。每个新项目至少需要明确：

- 起始提交、需求及待实现功能是否一致。
- 哪些文件是可信测试/配置，哪些属于候选必须实现的业务代码。
- 构建和测试工作目录、工具版本、依赖与锁文件、服务/数据库要求、端口及清理方式。
- 测试 ID、F2P/P2P 分组、报告格式、超时预算、评分规则。
- 是否允许新增依赖，可信配置覆盖会不会抹掉合法的任务修改。

当前方案适合以声明命令和文件映射复用验收执行器。新技术栈只要能输出支持的报告格式，通常无需新增案例专用 Python 逻辑；需要新报告格式或特殊服务生命周期时，才考虑扩展适配代码。基线校准与可信正例验证的作用是检查案例设计，不能由目录结构和哈希替代。
