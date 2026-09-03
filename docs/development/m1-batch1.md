# M1 首批开发交付：T1–T3

本批实现已批准计划的 T1–T3，不是完整 M1，也不是已经能自动调研的 Agent。

## 已实现

| 任务 | 交付 |
|---|---|
| T1 | 可安装 Python 包；模块/控制台帮助与版本入口；未实现命令返回非零退出码；限定打包范围 |
| T2 | ArtifactRef、Claim、ResearchBrief、DecisionInput、GateRecord、WorkspaceState、TaskResult；规范 JSON 哈希；类型化错误；路径校验 |
| T3 | 只读 CorpusAdapter；指定/当前快照；registry.snapshots → snapshot.releases → release → shard 校验；流式读原始记录 |

保留原始 `.gitignore` 内容，仅追加派生数据、私有数据和构建产物忽略规则。没有修改 corpus、DATASET_MANIFEST、导入器、旧完整性测试或已有设计文档。

### 重要边界

- FACT 目前只强制带有非空 Evidence ID；本批不证明引用存在或科学结论正确。
- Gate 只有数据契约与状态一致性校验；批准、事务保存、恢复及调度属于 T4–T7。
- 没有联网检索、全文解析、LLM、Idea、训练实验或完整 Skill。
- CorpusVerification.verified_files 统计具有预期哈希的 snapshot/release/shard 文件，不包含无上级预期哈希的 registry，也不代替根数据清单对原始抓取文件的全面检查。
- 迭代前预检整个指定快照，再逐分片重检。消费方应在迭代耗尽后发布下游产物；不可把部分迭代当作新的完整校验。
- 路径检查针对可信、单用户、不可变本地语料，拒绝静态链接与越界，但不是操作系统沙箱，不保证抵抗恶意本地进程竞态。

## 实际测试结果

| 检查 | 实测结果 |
|---|---|
| 源码/可编辑安装环境 | **113 passed, 1 skipped** |
| wheel 安装后的独立测试目录 | **113 passed, 1 skipped** |
| `python -m compileall -q research_agent` | 通过 |
| `git diff --check` | 通过 |
| 控制台 `research-agent --version` | `research-agent 0.1.0` |
| wheel 内容检查 | 18 个成员；只有 research_agent 和分发元数据，无 corpus/PDF/tests/workspaces |
| 旧 `node --test tests/conference-corpus.test.mjs` | 已尝试，但因完整仓库数据未挂载，在读取 DATASET_MANIFEST.json 时 ENOENT；未完成真实数据校验 |
| 真实 corpus Python 集成测试 | 1 项明确跳过，不计为通过 |

测试覆盖错误哈希、行数、快照身份、release 身份/年份、重复引用、未知快照、指定历史快照、Unicode U+2028/U+0085、保留扩展字段、非法 JSON、非有限数、路径越界、符号链接、只读字节/修改时间、错误枚举、非法审批和隐式日期转换。

复查追加了两组先失败后修复的测试：拒绝规范 JSON 中非字符串键被隐式改写；拒绝 ResearchBrief 日期被按 Unix 时间戳解释。测试日志与 JUnit XML 随本批源码交付包提供；机器可读摘要见 `m1-batch1-validation.json`。

这些是本地执行结果，不是 GitHub Actions 结果。本批进行了自检，尚未进行独立人工或独立模型代码评审。

## 执行环境与偏差

实测环境：Linux、Python 3.13.5、Node 22.16.0、Pydantic 2.13.4、PyYAML 6.0.3、filelock 3.29.0、pytest 9.0.2、setuptools 82.0.1。包声明 Python 3.11+，但本批未测试其他 Python 版本或操作系统。

本会话仍无法解析 GitHub 域名进行 git clone；通过 GitHub 连接读取基线，在独立本地 worktree 开发。原 `.gitignore` 与旧 Node 测试的 Git blob SHA 已与远程来源比对一致。完整 corpus 没有复制到本地。

离线安装复用宿主预装依赖，在新虚拟环境显式添加宿主 site-packages 路径，使用 `--no-index --no-deps --no-build-isolation`。这不是干净环境下重新解析全部依赖，也没有宣称完成 `[dev]` 全依赖安装；可选 build 前端未安装，wheel 通过 pip 调用 setuptools 后端构建。

## 当前可用命令

在依赖已安装的环境中，本批实测：

```bash
python -m pip install --no-index --no-deps --no-build-isolation -e .
python -m research_agent --version
research-agent --help
python -m pytest tests/agent -q -ra
```

正常联网开发环境可按计划安装 `python -m pip install -e '.[dev]'`，但该联网命令未在本批环境执行成功验证。

在有完整原始语料的仓库中执行实际验收：

```bash
node --test tests/conference-corpus.test.mjs
python -m pytest tests/agent/test_corpus.py -m real_corpus -q -ra
```

可通过 `RESEARCH_AGENT_CORPUS_ROOT` 指向完整仓库。未设置且未挂载语料时明确 skip；显式设置了无效路径则失败，不静默跳过。

Python 接口（在真实仓库根目录运行时会读取完整语料）：

```python
from pathlib import Path
from research_agent.adapters.corpus_adapter import CorpusAdapter

adapter = CorpusAdapter(Path("."))
report = adapter.verify()
print(report)
for record in adapter.iter_records(report.snapshot_id):
    # 原始 JSON 对象；未添加模型推断，不改写源文件。
    pass
```

## 后续边界

下一批为 T4–T5：事务化 Artifact/Event Store、恢复和真正的 Workspace/G1 操作。其前应在可获取全仓库的环境补跑真实 corpus 验收；不能用 fixture 测试代替。

本批应保持独立开发分支/草稿 PR，不自动合并 main。完整计划见 `../superpowers/plans/2026-09-03-research-story-agent-m1-plan.md`。
