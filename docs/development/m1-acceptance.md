# Research Story Agent M1 验收记录

- 里程碑：M1，T1–T8
- 分支：`feat/research-agent-m1`
- 状态：Ubuntu 与 macOS 自动验收均通过；等待独立代码审查；PR 继续保持 Draft。
- 最终跨平台验收日期：2026-09-04
- 当前验收分支头：`ec955f0013a68dd32e9ae55bfc6721bba03ff0d6`
- Ubuntu GitHub Actions run：`33749802029`
- macOS GitHub Actions run：`33825571151`（Research Agent CI #47）

## 1. 跨平台自动验收结果

### Ubuntu

环境：Ubuntu 24.04、CPython 3.12.14、Node.js 24.19.0。

```text
Node corpus inventory:
  2 passed, 0 failed, 0 skipped

Python fixture/unit/security/acceptance:
  183 passed, 1 real-corpus test deselected

Python real corpus integration:
  1 passed, 183 tests deselected

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
  184 passed

Protected repository diff:
  passed

Final CI worktree cleanliness:
  passed
```

`requirements-dev.lock` 在独立虚拟环境中安装，随后项目以 `--no-deps -e .` 安装并复跑全部 184 个 Python 测试。该锁定结果代表上述 Python/Linux 环境，不承诺所有平台使用相同二进制构建。

### macOS

环境：macOS 14.8.7、`macos-14-arm64` runner image、CPython 3.12.10、Node.js 24.18.0。

```text
Node corpus inventory:
  2 passed, 0 failed, 0 skipped

Python complete suite:
  184 passed in 8.58s

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

该 job 在 GitHub 托管的真实 macOS ARM64 环境中运行，满足 M1 的 macOS 平台验收。它不等同于覆盖每一台个人 Mac、所有 macOS 版本或用户本地配置；个人设备上的额外 smoke test 属于可选验证，不再作为本里程碑的发布阻塞条件。

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

## 3. T8 红—绿记录

T8 先增加攻击性测试，再修改生产代码。第一批测试首次执行时出现：

```text
4 failed, 176 passed
```

四个失败均指向同一个真实安全缺口：`ArtifactStore` 会跟随被替换成符号链接的 `artifacts/`、`commits/`、`recovery/` 或单个 Artifact 命名空间。

修复受控路径后，自动测试达到 183 个 Python 测试通过。最终差异自审又增加了一个更尖锐的用例：符号链接 Artifact 命名空间的外部目标已经包含伪造 `v*.json` 时，恢复流程也必须明确拒绝。该测试先出现：

```text
1 failed, 182 passed, 1 deselected
```

根因是恢复流程会静默忽略该符号链接命名空间。修复后，恢复会在孤儿扫描前验证所有 Artifact 命名空间，不跟随、不搬动外部目标文件；最终全量锁定环境达到 184 个 Python 测试通过。

## 4. T8 覆盖范围

- 两个独立进程竞争同一 Workspace，第二个操作得到类型化 `busy` 和退出码 6；
- `artifacts/`、`commits/`、`recovery/`、`.workspace.lock`、`events.jsonl`、`projection.json` 和 Artifact 命名空间的符号链接被拒绝；
- 符号链接 Artifact 命名空间包含伪造孤儿文件时，恢复拒绝并保持外部目标原样；
- 决策文件符号链接、重复 YAML key、隐式布尔、超大文件、未知字段和错误 actor 被拒绝；
- 私密输入和 Producer 异常正文不进入 CLI 错误输出或持久化事件；
- Artifact、commit marker、Event log 和 projection 的损坏及崩溃恢复；
- Event log 尾部半行可从 commit marker 恢复，中段损坏不会静默修复；
- G1 修订保留旧 ResearchBrief，旧 Gate 批准被拒绝；
- 创建、等待、批准、关闭、重新打开、恢复、S2 诚实阻塞；
- 工作流运行前后 corpus 以及除 `workspaces/` 外的 fixture 仓库文件保持不变；
- PR 相对 `main` 未修改 `corpus/`、`scripts/`、`DATASET_MANIFEST.json`、`DATA_NOTICE.md` 和原 Node 完整性测试；
- wheel 不包含 corpus、PDF、Workspace、cache、测试或密钥文件；
- Ubuntu 与 macOS ARM64 上的完整语料、测试、构建和 CLI 边界行为一致。

## 5. 当前能力边界

M1 完成的是运行时与研究治理底座：只读语料校验、不可变 Artifact、事件恢复、Workspace、G1、任务指纹、缓存和失效、API、Orchestrator 与 CLI。

M1 不包含 S2 检索、向量索引、外部检索、全文解析、LLM、领域图谱、研究机会、Idea、实验执行或 Skill。用户批准 G1 后调用 `run`，预期在 S2 返回：

```text
status: blocked
reason: stage_handler_not_installed
exit code: 5
```

这是有意的能力边界，不应解释为检索失败或空论文集合。

## 6. 工作区边界说明

GitHub Actions 使用干净 checkout，并在 Ubuntu 与 macOS job 末尾验证仓库状态为空。因此跨平台验收不受任何外部共享 checkout 中既有未提交修改影响。

如果某个开发者本地工作区已有未提交语料修改，例如：

```text
M corpus/releases/ICML/2026/release_7cfdc05e5558192e/papers.jsonl
```

不得由 M1 验收流程擅自恢复、覆盖或提交。应将其视为该本地工作区的独立状态，并优先在干净 worktree/clone 中继续开发或审查。

## 7. 剩余发布条件

在将 PR 从 Draft 转为可审阅或合并前，剩余必要步骤为：

1. 完成独立代码审查，重点检查持久化协议、路径边界、Gate 幂等、任务缓存/失效以及 CLI 错误语义；
2. 修复审查发现的 Critical/Important 问题，并重新运行 Ubuntu 与 macOS 验收；
3. 若审查无阻塞问题，将 PR 从 Draft 转为 Ready for review；
4. 在确认分支头未变化且检查仍为绿色后，决定是否合并到 `main`。

个人实体 Mac 上的额外运行可以增加对特定机器配置的信心，但 GitHub 托管 `macos-14-arm64` 已完成本里程碑所要求的 macOS 平台级验证。

本记录不自动批准真实研究课题，也不自动合并 `main`。