# Research Story Agent M1 验收记录

- 里程碑：M1，T1–T8
- 分支：`feat/research-agent-m1`
- 状态：Ubuntu 与 macOS 跨平台验收通过；合并前内部技术审查发现的问题已修复并复验；等待独立代码审查；PR 继续保持 Draft。
- 跨平台验收日期：2026-09-04
- macOS 验收提交：`ec955f0013a68dd32e9ae55bfc6721bba03ff0d6`
- 合并前内部审查修复提交：`240e8c57ee877b210190b2fc9c228b21b7e73924`
- 初始跨平台验收 run：`33825571151`（Research Agent CI #47）
- 审查回归红灯 run：`33826936711`（Research Agent CI #49）
- 审查修复绿灯 run：`33827199882`（Research Agent CI #53）

> “内部技术审查”指本轮对 PR 实现进行的系统化自审、回归测试和修复，不等同于由另一名工程师完成的独立代码审查或 GitHub 审批。

## 1. 最终跨平台自动验收

### Ubuntu

审查修复后的最终环境：Ubuntu 24.04、CPython 3.12.14、Node.js 24.19.0。

```text
Node corpus inventory:
  2 passed, 0 failed, 0 skipped

Python fixture/unit/security/acceptance:
  189 passed, 1 real-corpus test deselected

Python real corpus integration:
  1 passed, 189 tests deselected

Python compileall:
  passed

Source/wheel build:
  passed

Wheel content audit:
  passed, 28 entries

Real CLI smoke:
  corpus verify passed
  Workspace creation passed
  persisted status reopen passed
  unapproved G1 remained waiting_for_user

Fresh locked environment:
  190 passed

Protected repository diff:
  passed

Final CI worktree cleanliness:
  passed
```

`requirements-dev.lock` 在独立虚拟环境中安装，随后项目以 `--no-deps -e .` 安装并复跑全部 190 个 Python 测试。该锁定结果代表上述 Python/Linux 环境，不承诺所有平台使用相同二进制构建。

### macOS

审查修复后的最终环境：macOS 14.8.7、`macos-14-arm64` runner image、CPython 3.12.10、Node.js 24.18.0。

```text
Node corpus inventory:
  2 passed, 0 failed, 0 skipped

Python complete suite:
  190 passed in 13.20s

Python compileall:
  passed

Source/wheel build:
  passed
  research_story_agent-0.1.0.tar.gz
  research_story_agent-0.1.0-py3-none-any.whl

Wheel content audit:
  passed, 28 entries

Real macOS CLI flow:
  corpus verify passed
  Workspace created at G1 / waiting_for_user
  G1 approval advanced to S2 / not_started
  pending_gate became null
  validation returned valid=true
  cross-command state recovery passed
  events included WorkspaceCreated, GateOpened and GateApproved
  S2 returned blocked / stage_handler_not_installed
  S2 exit code was 5

Final macOS CI worktree cleanliness:
  git diff --check passed
  git status --short was empty
```

GitHub 托管的真实 macOS ARM64 runner 已满足 M1 的 macOS 平台验收。它不等同于覆盖每一台个人 Mac、所有 macOS 版本或用户本地配置；个人设备上的额外 smoke test 属于可选验证，不再作为本里程碑的发布阻塞条件。

## 2. 真实语料身份

Ubuntu 与 macOS job 均在完整仓库上核验：

```text
snapshot_id: snapshot_a6ef56370e3258f5
snapshot_checksum: ee7d5a78248419e8cb31a4070b4430e3a492c565418e21766bef7b870ea2391e
paper_count: 113989
release_count: 86
verified_files: 173
```

Node 原完整性测试和 Python `CorpusAdapter` 真实集成测试均通过。该验收确认文件哈希、层级身份、JSONL 可解析性和计数一致性，不代表逐篇验证论文科学内容。

## 3. T8 安全红—绿记录

T8 首先增加攻击性测试，第一批红灯为：

```text
4 failed, 176 passed
```

四个失败指向同一个安全缺口：`ArtifactStore` 会跟随被替换成符号链接的 `artifacts/`、`commits/`、`recovery/` 或单个 Artifact 命名空间。

修复受控路径后，最终差异自审又增加“符号链接 Artifact 命名空间内已有伪造 `v*.json`”用例，得到：

```text
1 failed, 182 passed, 1 deselected
```

恢复流程随后改为先枚举并验证全部 Artifact 命名空间，再处理孤儿文件；外部目标不会被跟随或搬动。

## 4. 合并前内部技术审查红—绿记录

在初始 Ubuntu/macOS 验收之后，对 API、CLI、持久化路径及 Workspace 状态关系进行逐文件审查，并先提交六个回归测试。CI #49 在 Ubuntu 与 macOS 上均按预期失败；Ubuntu 摘要为：

```text
6 failed, 183 passed, 1 real-corpus test deselected
```

六项问题及修复如下：

1. `validate` 在 Workspace 被其他进程占用时，将 `busy` 错误压缩为 `valid=false` 和退出码 4。修复后保留类型化 `busy` 与退出码 6。
2. `research-agent --json` 未给出子命令时输出普通帮助并返回 0。修复后只输出一个结构化 `input_error` JSON 并返回 2；非 JSON 模式仍显示帮助。
3. 单个 commit marker 文件可被替换为符号链接并被读取。修复后 marker 必须通过安全子路径解析并为常规文件。
4. 派生的 `workspace.yaml` 可被替换为符号链接。修复后读写 projection 前通过安全子路径验证，拒绝跟随外部目标。
5. 重新打开 Workspace 时未核对 ResearchBrief 的 `target_venue` 与冻结 DomainProfile。修复后不一致会被判为完整性错误。
6. 重新打开 G1 Workspace 时未核对 pending Gate 是否绑定当前 ResearchBrief 引用。修复后 Gate/Brief 版本或哈希错配会被拒绝。

同一修复还加强了：

- `effective_config` 与 `research_brief` 的 Artifact ID 必须精确匹配；
- Brief 的核心二维、2.5D、3D、切片与主任务边界不得超出冻结 DomainProfile；
- `scope.focus` 等非核心扩展字段仍可保留，不因边界核验被不必要删除。

CI #53 在相同两类平台上完成绿灯：Ubuntu 锁定环境 190 项通过，macOS 完整套件 190 项通过；语料、构建、wheel、真实 G1/S2 CLI 边界及干净工作区检查均继续通过。

## 5. T8 与内部审查覆盖范围

- 两个独立进程竞争同一 Workspace，第二个操作得到类型化 `busy` 和退出码 6；
- `validate` 不再把暂时占用误报为损坏；
- JSON CLI 的成功与输入错误路径保持机器可读；
- `artifacts/`、`commits/`、`recovery/`、控制文件、单个 marker、Workspace projection 和 Artifact 命名空间的符号链接被拒绝；
- 符号链接 Artifact 命名空间包含伪造孤儿文件时，恢复拒绝并保持外部目标原样；
- 决策文件符号链接、重复 YAML key、隐式布尔、超大文件、未知字段和错误 actor 被拒绝；
- 私密输入和 Producer 异常正文不进入 CLI 错误输出或持久化事件；
- Artifact、commit marker、Event log 和 projection 的损坏及崩溃恢复；
- Event log 尾部半行可从 commit marker 恢复，中段损坏不会静默修复；
- G1 修订保留旧 ResearchBrief，旧 Gate 批准被拒绝；
- 重启时重新核验冻结配置、ResearchBrief、pending Gate 与 Workspace 状态关系；
- 创建、等待、批准、关闭、重新打开、恢复、S2 诚实阻塞；
- 工作流运行前后 corpus 以及除 `workspaces/` 外的 fixture 仓库文件保持不变；
- PR 相对 `main` 未修改 `corpus/`、`scripts/`、`DATASET_MANIFEST.json`、`DATA_NOTICE.md` 和原 Node 完整性测试；
- wheel 不包含 corpus、PDF、Workspace、cache、测试或密钥文件；
- Ubuntu 与 macOS ARM64 上的完整语料、测试、构建和 CLI 边界行为一致。

## 6. 当前能力边界

M1 完成的是运行时与研究治理底座：只读语料校验、不可变 Artifact、事件恢复、Workspace、G1、任务指纹、缓存和失效、API、Orchestrator 与 CLI。

M1 不包含 S2 检索、向量索引、外部检索、全文解析、LLM、领域图谱、研究机会、Idea、实验执行或 Skill。用户批准 G1 后调用 `run`，预期在 S2 返回：

```text
status: blocked
reason: stage_handler_not_installed
exit code: 5
```

这是有意的能力边界，不应解释为检索失败或空论文集合。

## 7. 工作区边界说明

GitHub Actions 使用干净 checkout，并在 Ubuntu 与 macOS job 末尾验证仓库状态为空。因此跨平台验收不受任何外部共享 checkout 中既有未提交修改影响。

如果某个开发者本地工作区已有未提交语料修改，例如：

```text
M corpus/releases/ICML/2026/release_7cfdc05e5558192e/papers.jsonl
```

不得由 M1 验收流程擅自恢复、覆盖或提交。应将其视为该本地工作区的独立状态，并优先在干净 worktree/clone 中继续开发或审查。

## 8. 剩余发布条件

在将 PR 从 Draft 转为可审阅或合并前，剩余必要步骤为：

1. 由独立审查者完成代码审查，重点检查持久化协议、路径边界、Gate 幂等、任务缓存/失效及 CLI 错误语义；
2. 修复独立审查发现的 Critical/Important 问题，并重新运行 Ubuntu 与 macOS 验收；
3. 若独立审查无阻塞问题，将 PR 从 Draft 转为 Ready for review；
4. 在确认最终分支头未变化且检查仍为绿色后，再决定是否合并到 `main`。

本记录不自动批准真实研究课题，也不自动合并 `main`。
