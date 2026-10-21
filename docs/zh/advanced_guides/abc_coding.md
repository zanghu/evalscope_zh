# ABC Coding：本地 OpenCode HTTP 开发任务

`abc_coding` 将本地 JSONL 索引中的每个案例作为一个 EvalScope 样本，复用标准加载、抽样、重复、预测记录、评分聚合和输出目录管理。默认只开发；可配置开发后验收、已有候选验收或起始代码基线校准。

从 Git 分支制作输入案例包，请参阅[手工整理案例包操作说明](abc_coding_case_preparation.md)。

## 安装与前提

从源码安装 EvalScope，确保当前终端可以运行 Git 和 OpenCode。HTTP 接口按本机 OpenCode 1.18.31 的 `/doc` 核对，其他版本需验证 `/permission`、`/question` 和会话接口兼容性。

OpenCode 使用自己的 provider 凭据，调用不经过 EvalScope Bridge。不要在案例或配置文件中保存密钥。HTTP Basic Auth 密码通过 `OPENCODE_SERVER_PASSWORD`（或 `password_env` 指定的环境变量）读取。

`eval_type: mock_llm` 仅是 EvalScope 的未使用模型占位符，不代表 OpenCode 使用模拟模型；真实模型由 `extra_params.opencode.provider_id/model_id` 指定。

## 数据结构

```text
evalscope_cases/
  default_test.jsonl
  litemall-pr534/
    case.json
    task.md
    source/initial/             # 已展开、无 .git 的代码目录
    validation/source-files.json
    verifier/                  # 不复制到开发目录
```

索引每行一条：

```json
{"case_id":"litemall-pr534","case_manifest":"litemall-pr534/case.json"}
```

索引路径相对数据集根目录；案例资源相对 `case.json` 所在目录。案例描述保留原字段，并新增：

```json
{
  "development": {
    "source_directory": "source/initial",
    "source_checksums": "validation/source-files.json",
    "working_directory": ".",
    "task_sha256": "需求文件的64位SHA256"
  }
}
```

`source-files.json` 是源代码目录中所有文件的 `{相对路径: SHA256}` 映射。准备时核对完整清单，拒绝额外或缺失文件、链接以及 Git 历史。输入案例需由评测组织者审核；哈希只能检测一致性，不构成真实性签名。

## 批量配置

参见 `examples/abc_coding/opencode.json`。复制配置后调整数据集与输出的绝对路径、provider/model、可执行文件和权限策略：

```powershell
evalscope eval --task-config E:\custom_benchmark\configs\abc-coding-opencode.json
```

若终端中的 `evalscope` 仍来自旧版安装，直接从当前源码目录使用同一 CLI：

```powershell
Set-Location E:\code\evalscope
python -m evalscope.cli.cli eval --task-config E:\custom_benchmark\configs\abc-coding-opencode.json
```

`--task-config` 直接调用已有完整任务文件加载器，文件中的配置具有完整控制权，其他单项 CLI 参数不覆盖它；不要与 `--eval-config` 混用。原有 `--eval-config` 是非原生后端配置，不是完整 TaskConfig。

首次项目初始化可能加载插件，`session_timeout` 默认 120 秒；普通请求使用 `request_timeout`（默认 15 秒）。两者独立于模型执行预算 `timeout`。超时停止还需要取消确认时间。

首版要求 `eval_batch_size=1`，不支持 `use_cache` 恢复。标准 `limit`、`repeats` 仍可使用。每次尝试使用唯一目录和新会话；`start_server=true` 为每个尝试启动专用隐藏服务并在结束后关闭，`false` 连接已有服务且不关闭它。自动启动遇到已存在的服务会报错，不接管用户进程。

`permissions` 是 OpenCode 会话权限规则数组。默认空数组继承现有配置；出现待确认权限或问题时取消本次任务并记录 `needs_input`，不会无限等待或自动批准。示例允许常用开发工具、拒绝访问工作目录外部；这不是操作系统安全隔离，特别是 shell 本身仍具有本机账户权限。

依赖安装由智能体在工作目录内执行，计入任务时间；本版本不会提前自动运行 npm ci 或 Maven。Node/JDK/浏览器等工具需预装。正式环境可在发布案例时明确统一准备政策。

## 执行与产物

每次尝试位于 `<work_dir>/<timestamp>/artifacts/abc_coding/<case_id>/<attempt_id>/`：

- `workspace/`：保留的开发工作区和新 Git 基线。
- `execution.json`：执行状态、模型、版本、预算实际耗时、输入哈希和错误。
- `session.json`：OpenCode 返回的原始消息和结果；可观察的模型文本和工具事件转换为标准 AgentTrace，保存于 EvalScope review。
- `candidate.patch`、`candidate.zip`、`candidate.json`：相对固定基线的二进制补丁、完整候选代码及哈希。
- `run-config.json`：非密钥连接配置。
- `opencode-server.log`：仅自动启动时产生。

候选归档保留基线已跟踪文件，包含新文件和智能体自己提交的修改；新产生的 Git 忽略文件、常见依赖/构建目录、`.env*`、日志和密钥扩展文件不归档。新业务文件若被这些规则排除，必须调整政策后重跑，不要用不完整产物进行最终验收。

`batch-execution.json` 保存当前批次的逐项状态。`completed` 只代表对应会话正常结束，不能证明需求完成。`error`、`timed_out`、`needs_input` 记录后继续其他案例；如果取消无法确认，则停止批次且不归档可能仍变化的候选。保持 `ignore_errors=false`，不要绕过这一保护。

仅开发模式返回 `ScoreStatus.EXCLUDED` 和空分值，框架生成无功能分数的报告；UI 可能显示排除/未完成评测。以 `execution.json` 查看开发状态。

## 第3步：简化可信验收

`dataset_args.abc_coding.extra_params.coding` 使用以下模式：

| mode | 行为 |
| --- | --- |
| `develop` | 默认，仅调用 OpenCode 开发 |
| `develop_and_verify` | 开发后执行验收，输出功能评分 |
| `verify_only` | 从 `candidates` 映射读取已有 attempt 目录，不启动 OpenCode |
| `verify_baseline` | 对案例初始快照运行同一测试，仅用于校准，单独报告 |

`verify_only` 的 `candidates` 为 `{ "案例ID": "包含 execution.json、candidate.json、candidate.zip 的目录" }`。
每次独立验收都创建新 EvalScope 运行目录，原开发目录保持不变；通过 development_attempt_id 关联。
这不是 `use_cache` 或 `rerun_review`，不依赖它们恢复流程。不要混合不同案例版本的结果。

本机配置示例：

```powershell
# 验收 20260918_120507 的现有候选，不调用模型
python -m evalscope.cli.cli eval --task-config E:\custom_benchmark\configs\abc-coding-verify.json
# 校准初始代码，预期目标功能测试失败
python -m evalscope.cli.cli eval --task-config E:\custom_benchmark\configs\abc-coding-baseline.json
# 下一次开发和验收一并执行，会调用模型
python -m evalscope.cli.cli eval --task-config E:\custom_benchmark\configs\abc-coding-full.json
```

案例 `case.json` 增加 `verification`：独立 `version`、`working_directory`、覆盖清单和测试清单路径、环境变量、预检端口、`steps`。
每阶段声明 name、kind（setup/gate/tests）、command 参数数组、timeout。tests 阶段另声明 report_format（jest/junit）和 report_path（相对工作目录）。
测试清单的 suite 必须对应阶段 name，每项必需测试提供唯一 id 和 group。F2P/P2P 支持分组通过率。
命令直接执行，不拼接 shell；Windows npm 自动解析为 Node/npm-cli.js。其他 shell 脚本应显式声明解释器和参数。

验收只做以下检查：候选版本、任务及源清单身份、候选 ZIP 哈希、安全解压、覆盖清单内可信文件哈希、测试清单完整性，以及运行结束后可信文件复查。不进行全仓库差异审计，不自动合并依赖配置。
验收材料在验收时固定并记录摘要；历史开发产物尚未绑定验收摘要，不能据此证明开发时已固定同一版验收材料。

为避免 Windows 长路径，验收工作区使用 `<本次输出>/artifacts/verification/<短验证ID>/workspace/`。
同级保存 recipe.json、overlay-manifest.json、test-inventory.json、logs 和 verification.json；测试报告、截图、Playwright trace 保留在验收工作区的测试工具输出目录。
`artifacts/abc_coding/batch-verification.json` 包含全部验收记录引用、总数、有效数、解决率、覆盖率及异常数。

首版使用已有 Playwright webServer 负责 Vue 开发服务器的启动、就绪等待和正常退出清理，不需要 Java/MySQL。
每个命令超时会终止其进程树；无法确认清理时异常向上传播并停止批次。案例脚本不得自行启动脱离命令生命周期的后台服务。
本地进程不是安全沙箱；外部工具缓存、OpenCode 全局数据不保证都在运行目录内。

所有必需测试恰好出现一次且通过、无其他失败、门槛命令成功，才记 resolved=1。完整断言失败记0；报告缺失、跳过、重复、报告与退出码冲突或可信文件变化记 needs_review，不产生 resolved。明确端口占用或命令缺失记 infrastructure_error。
依赖安装失败、编译/类型检查非零、验收超时若无法确定原因，保守记 needs_review，日志用于人工确认；首版不猜测故障归因，也不自动重试到通过。
Score 始终提供 evaluation_coverage=0/1；不可判定时省略 resolved 和分组指标，绝不写0冒充失败。基线校准的 resolved=0 通常符合预期，不是模型成绩。

现有服务可扫描这些标准报告和 review：

```powershell
python -m evalscope.cli.cli service --host 127.0.0.1 --outputs E:\custom_benchmark\runs
```

HTML 汇总位于 reports/report.html，Web 详情使用标准 AgentTrace。原始会话和附件路径保存在 review 元数据中；不新增附件下载接口或内嵌 Playwright trace 查看器。
首版不使用 LLM Judge；以后应通过 EvalScope JudgeDefinition/OutputContract 扩展独立指标。

## 验证

```powershell
python -m pytest tests/agent/test_opencode_http.py tests/benchmark/test_abc_coding.py -q
```

自动化测试使用 HTTP 模拟和临时项目，不调用付费模型。真实联调应使用小型临时项目独立执行；正式运行前确认服务版本、provider/model 可用以及权限策略。
