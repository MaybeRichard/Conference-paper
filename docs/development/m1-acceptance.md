# Research Story Agent M1 验收记录

- 里程碑：M1，T1–T8
- 分支：`feat/research-agent-m1`
- 状态：自动验收通过；等待研究者在 macOS 上完成最终本地确认；PR 继续保持 Draft。
- 自动验收日期：2026-09-03
- 主要实现验收提交：`2968966d22aa950d63d46ba42e793cb73df7befb`
- GitHub Actions run：`33749605435`
- 环境：Ubuntu 24.04、CPython 3.12.14、Node.js 24.20.0

## 1. 自动验收结果

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

`requirements-dev.lock` 在独立虚拟环境中安装，随后项目以 `--no-deps -e .` 安装并复跑全部 184 个 Python 测试。锁定结果代表上述 Python/Linux 环境，不宣称所有平台使用相同二进制构建。

## 2. 真实语料身份

自动验收在完整仓库上核验：

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
- wheel 不包含 corpus、PDF、Workspace、cache、测试或密钥文件。

## 5. 当前能力边界

M1 完成的是运行时与研究治理底座：只读语料校验、不可变 Artifact、事件恢复、Workspace、G1、任务指纹、缓存和失效、API、Orchestrator 与 CLI。

M1 不包含 S2 检索、向量索引、外部检索、全文解析、LLM、领域图谱、研究机会、Idea、实验执行或 Skill。用户批准 G1 后调用 `run`，预期在 S2 返回：

```text
status: blocked
reason: stage_handler_not_installed
exit code: 5
```

这是有意的能力边界，不应解释为检索失败或空论文集合。

## 6. 剩余发布条件

在将 PR 从 Draft 转为可审阅或合并前，仍建议完成：

1. 研究者在 macOS / Python 3.12.13 / Node.js 24.19.0 上拉取最终分支头并按 `m1-quickstart.md` 复跑一次；
2. 手动创建一个真实 Workspace，查看当前 G1，明确批准，再由新进程确认 S2 诚实阻塞和 Workspace 验证；
3. 独立代码审查，重点检查持久化协议、路径边界、Gate 幂等及 CLI 错误语义；
4. 根据审查结果决定保持 Draft、转 Ready for review 或合并。

本记录不自动批准真实研究课题，也不自动合并 `main`。
