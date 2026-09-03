# Research Story Agent M1 Quickstart

## 当前能力边界

M1 是可恢复、可审计的研究工作流底座。它当前能够：

```text
验证固定 corpus snapshot
→ 创建 Workspace
→ 冻结 medical_diffusion_2d 配置与 ResearchBrief
→ 停在 G1 等待用户
→ 修订或批准精确版本的 G1
→ 跨进程恢复状态
→ 在尚未实现的 S2 检索阶段诚实阻塞
```

M1 **尚不包含**论文检索、向量索引、外部搜索、PDF 全文精读、LLM 调用、痛点分析、Idea 生成、实验执行或完整对话式 Skill。`S2 / stage_handler_not_installed` 是当前预期边界，不是已经完成检索。

本 Quickstart 面向当前 Draft PR 的 `feat/research-agent-m1` 分支。PR 合并前不要把这些命令当作 `main` 已发布接口。

## 1. 安装

要求 Python 3.11 或更高版本。完整 corpus 验收还需要 Node.js 24。

```bash
git switch feat/research-agent-m1
git pull --ff-only origin feat/research-agent-m1

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

复现 CI 中锁定的 Python 3.12 开发依赖时，可改用：

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
```

`requirements-dev.lock` 记录的是 Ubuntu 24.04 / CPython 3.12.14 上实际解析和测试的版本，不承诺所有 Python/操作系统均使用相同二进制组合。

检查入口：

```bash
research-agent --version
research-agent --help
```

## 2. 验证只读语料快照

在仓库根目录执行：

```bash
research-agent --repo "$PWD" --json corpus verify
```

当前仓库的预期身份是：

```text
snapshot_id: snapshot_a6ef56370e3258f5
paper_count: 113989
release_count: 86
verified_files: 173
```

命令会检查 registry、snapshot、release、JSONL 行数与 SHA-256。它验证数据库存与结构完整性，不验证每篇论文内容的科学真实性。

## 3. 创建 Workspace

```bash
research-agent \
  --repo "$PWD" \
  --json \
  workspace create \
  --domain medical_diffusion_2d \
  --topic "二维医学图像扩散生成"
```

输出应包含：

```json
{
  "workspace_id": "ws_YYYYMMDD_xxxxxxxxxxxx",
  "stage": "G1",
  "status": "waiting_for_user",
  "pending_gate": {
    "gate_id": "gate_g1_xxxxxxxxxxxxxxxxxxxx",
    "artifact": {
      "artifact_id": "research_brief",
      "version": 1,
      "sha256": "..."
    }
  }
}
```

将实际 `workspace_id` 保存到 shell：

```bash
export WS="替换为实际 workspace_id"
```

运行状态只写入：

```text
workspaces/<workspace-id>/
```

该目录默认被 Git 忽略。`corpus/`、manifest、导入脚本和原始测试不会被研究运行写入。

## 4. 查看状态与 G1

```bash
research-agent --repo "$PWD" --json status "$WS"
research-agent --repo "$PWD" --json gate show "$WS"
```

未批准时重复执行 `run` 不会绕过 G1：

```bash
research-agent --repo "$PWD" --json run "$WS" --until next-gate
```

预期仍返回 `waiting_for_user`，退出码为 0。

## 5. 可选：修订 ResearchBrief

根据 `gate show` 的当前 Artifact 引用手动创建 `g1-revision.yaml`：

```yaml
expected:
  artifact_id: research_brief
  version: 1
  sha256: 替换为当前完整 SHA-256

changes:
  topic: 二维病灶条件扩散生成
  scope:
    allow_independent_ct_mri_slices: false
```

执行：

```bash
research-agent \
  --repo "$PWD" \
  --json \
  gate revise "$WS" \
  --revision g1-revision.yaml
```

修订会保留 v1，创建 v2 和新 Gate。旧 Gate 的批准文件随后必须被拒绝。该领域配置允许继续收窄范围，但不允许启用 2.5D 或 3D。

## 6. 明确批准 G1

再次运行 `gate show`，把当前 `gate_id` 与 Artifact 引用手动复制到 `g1-decision.yaml`：

```yaml
request_id: g1_approval_001
gate_id: 替换为当前 gate_id
artifact:
  artifact_id: research_brief
  version: 替换为当前版本
  sha256: 替换为当前完整 SHA-256
actor: user
action: approve
```

批准是研究者决定；生产 Orchestrator 不会自动生成或代签该文件。

```bash
research-agent \
  --repo "$PWD" \
  --json \
  gate approve "$WS" \
  --decision g1-decision.yaml
```

成功后预期：

```text
stage: S2
status: not_started
pending_gate: null
```

## 7. 验证重启恢复与诚实阻塞

打开新终端，重新激活环境并运行：

```bash
source .venv/bin/activate
research-agent --repo "$PWD" --json status "$WS"
research-agent --repo "$PWD" --json validate "$WS"
research-agent --repo "$PWD" --json events "$WS"
```

然后尝试推进：

```bash
set +e
research-agent --repo "$PWD" --json run "$WS" --until next-gate
RUN_EXIT=$?
set -e
printf 'run exit: %s\n' "$RUN_EXIT"
```

M1 的预期结果是：

```json
{
  "stage": "S2",
  "status": "blocked",
  "reason": "stage_handler_not_installed",
  "new_artifacts": []
}
```

预期退出码为 5。随后 `status` 仍应为 `S2 / not_started`；阻塞结果不会伪造或持久化为检索成功。

## 8. 开发与验收命令

```bash
python -m pytest tests/agent -q -m 'not real_corpus'
python -m pytest tests/agent -q -m real_corpus
node --test tests/conference-corpus.test.mjs
python -m compileall -q research_agent
python -m build
```

检查 wheel 不包含 corpus、PDF、Workspace、密钥或测试数据：

```bash
python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

wheels = sorted(Path("dist").glob("*.whl"))
assert len(wheels) == 1, wheels
with ZipFile(wheels[0]) as archive:
    names = archive.namelist()
forbidden = ("corpus/", "workspaces/", "cache/", ".env", ".pdf", "tests/")
assert not [name for name in names if any(item in name for item in forbidden)]
assert any(name == "research_agent/api.py" for name in names)
print(f"verified wheel entries: {len(names)}")
PY
```

`python -m build` 产生的 `build/` 和 `dist/`、运行产生的 `workspaces/` 均被忽略。验收后仍应检查：

```bash
git diff --check
git status --short
```

## 9. 已验证范围与安全说明

T8 自动测试覆盖：

- 不可变 Artifact、commit marker 与 Event log 恢复；
- 日志半行恢复和中段损坏拒绝；
- 损坏 Artifact/marker 的完整性错误；
- 两个独立进程竞争同一 Workspace 时的锁超时；
- `artifacts/`、`commits/`、`recovery/`、控制文件和 Artifact 命名空间的符号链接拒绝；
- 决策 YAML 的重复键、未知字段、隐式布尔、超大文件和符号链接拒绝；
- 私密输入与 Producer 异常消息不进入 CLI 错误或持久化事件；
- G1 版本、哈希、actor、request ID、修订和过期批准；
- 创建、批准、关闭、重启、恢复、S2 阻塞及 corpus 不变。

威胁模型仍是可信单用户本地文件系统。系统降低路径穿越和已存在符号链接风险，但不宣称抵御拥有同等本地权限的恶意进程在系统调用之间实施的全部 TOCTOU 攻击，也不保证远程文件系统断电语义。

## 10. 下一里程碑

M1 验收完成后，M2 才会接入真正的本地关键词/语义索引、查询扩展、范围筛选、覆盖报告和 G2。embedding、外部搜索与筛选模型也在 M2 单独选择和验证，不在 M1 中以空实现占位。
