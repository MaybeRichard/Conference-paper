# Research Story Agent M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Only select an execution mode actually supported by the host; do not simulate subagents.

**Goal:** 交付一个不依赖大模型、GPU 或网络服务的可运行底座：验证真实 corpus、创建二维医学扩散研究课题、停在 G1、保存用户批准、重启恢复，并在尚未实现的 S2 明确阻塞。

**Architecture:** 延续已批准的 Python API → Orchestrator → 受控状态与存储架构。采用只读 CorpusAdapter、版本化 JSON Artifact、提交清单与事件日志；CLI 是 API 的薄封装。四个 Gate 的转换规则可测试，但 M1 不伪造 G2–G4 的科研材料。

**Tech Stack:** Python 3.11+；标准库 argparse、json、hashlib、pathlib、datetime、uuid；Pydantic 2、PyYAML 6、filelock 3；pytest。上述版本是本里程碑选择，不是设计稿已有版本要求；在实际执行环境解析依赖并记录精确版本后才宣称可复现。

**Spec:** `docs/superpowers/specs/2026-09-02-research-story-agent-design.md`，设计基线提交 `7ca629eaf843f70b319f990129121d7f0deca785`。用户已在对话中确认整合稿。该设计文件保持原样，本计划记录确认后的实施交接。

## Global Constraints

以下原文约束继承自已批准设计：

- “首个领域配置：`medical_diffusion_2d`。”
- “首个验证课题：二维医学图像扩散生成与合成。”
- “首选投稿场景：MICCAI。”
- “核心包通过文件系统写入范围和接口限制实现只读边界，而不是只写一句 Prompt。”
- “批准绑定 `gate_id + artifact_version + content_hash`，不是泛化的‘以后都同意’。”
- “角色不得自动批准。”
- “禁止把未评价写成失败；禁止把搜索未命中写成无人研究；禁止把预计结果写成实验结果。”
- “保留现有文件路径和测试入口。尤其不在添加 Agent 的同时迁移或重写已有完整性测试。”
- “数量区间是充分覆盖时的目标，不是通过验收必须填充的内容。”

M1 不实现语义检索、联网检索、PDF 解析、LLM、Idea、实验执行、Web 或完整 Skill。其余设计要求按文末 M2–M5 映射交付，不被删除。

---

## 执行前检查与交付方式

1. 在真实仓库先读 `AGENTS.md` 等实际存在的工作区指令，重读 Spec 和本计划。
2. 核对当前 HEAD；允许其比设计基线多出本计划文档，不能强行 reset 用户的新提交。
3. 使用宿主支持的隔离工作区或 git worktree，在 `feat/research-agent-m1` 开发；不直接在 main 开发，不自动合并。
4. 首先运行 `node --test tests/conference-corpus.test.mjs`。失败则保留日志、报告基线问题，不能改数据或测试常量让它通过。
5. 按任务逐项执行“失败测试 → 最小实现 → 通过测试 → 小提交”。每个任务有单独可验收产物。
6. 最终交付代码分支/PR、测试日志和 M1 使用说明。只有真实测试通过才能标记任务完成。

本计划编写时已通过 GitHub 读取真实 registry、snapshot、release manifest、原完整性测试和 `.gitignore`。本会话容器无法解析 GitHub 主机名，未能克隆全仓库，因此没有执行原始 corpus 测试，也没有执行尚不存在的 M1 测试。以下 PASS 均是实施时的预期，不是已取得的结果。

## M1 的可见成果

```text
创建课题 → 读取真实快照 → 固化二维配置 → 等待 G1
→ 用户明确批准 → 新进程读取相同决定 → 尝试推进
→ 在 S2 返回 blocked / stage_handler_not_installed
```

用户不需要先提供模型密钥或 GPU。G1 的 Brief 由已批准领域配置与用户输入确定性组装，标记 `creation_basis=profile_and_user_input`，不声称完成了语义研究框定。

## 文件职责图

| 文件 | 职责 | 任务 |
|---|---|---|
| `pyproject.toml` | 安装、依赖范围、入口和 pytest 配置 | T1 |
| `research_agent/__init__.py`, `__main__.py`, `cli.py` | 包版本、模块入口和 CLI 薄层 | T1/T7 |
| `research_agent/schemas/base.py`, `research.py`, `workflow.py` | Artifact、证据基础、Brief、Gate 和任务契约 | T2 |
| `research_agent/core/errors.py`, `serialization.py`, `paths.py` | 类型化错误、规范 JSON、路径限制 | T2 |
| `research_agent/adapters/corpus_adapter.py` | 按真实 manifest 只读校验和迭代 | T3 |
| `research_agent/core/store.py` | 不可变产物、事务、事件与恢复 | T4 |
| `research_agent/core/state_machine.py`, `gates.py` | 纯状态转换、版本化用户决定 | T5 |
| `research_agent/core/workspace.py` | 课题创建、领域配置、快照绑定 | T5 |
| `domains/medical_diffusion_2d/domain.yaml` | 已确认范围，不包含科研结论 | T5 |
| `research_agent/core/tasks.py`, `dependencies.py` | fingerprint、复用、失败和失效传播 | T6 |
| `research_agent/core/orchestrator.py`, `api.py` | API 统一业务入口与阶段调度 | T7 |
| `tests/agent/` | M1 单元/集成/安全与故障测试 | T1–T8 |
| `docs/development/m1-quickstart.md` | 经运行核验的命令和能力边界 | T8 |
| `requirements-dev.lock` | 执行时实际解析的精确开发依赖 | T8 |

各新增 Python 子包添加必要 `__init__.py`。M1 不创建空的 retrieval、reading、ideation 类，不移动既有测试。`README.md` 的其他内容和历史数据文档修正不混入本次功能分支。

---

## T1：可安装包与诚实的命令入口

**Files:** 创建 `pyproject.toml`、`research_agent/__init__.py`、`research_agent/__main__.py`、`research_agent/cli.py`、`tests/agent/test_package.py`；修改 `.gitignore` 末尾追加开发产物规则。

**Interfaces:** `research_agent.__version__ = "0.1.0"`；`research_agent.cli.main(argv: list[str] | None = None) -> int`。后续命令在 T7 扩展同一入口。

- [ ] 写失败测试：

```python
import subprocess
import sys


def test_module_version():
    result = subprocess.run(
        [sys.executable, "-m", "research_agent", "--version"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "research-agent 0.1.0"
```

- [ ] 运行 `python -m pytest tests/agent/test_package.py -q`；预期因包尚不存在失败。先安装 pytest 等测试工具，避免把缺少 pytest 当作有效红灯。
- [ ] 最小实现：argparse 的 `--version`；`__main__.py` 通过 `raise SystemExit(main())` 调用；配置仅打包 `research_agent*`，不把 corpus/PDF 收进 wheel。

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "research-story-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2,<3", "PyYAML>=6,<7", "filelock>=3,<4"]

[project.optional-dependencies]
dev = ["pytest>=8,<10", "build>=1,<2"]

[project.scripts]
research-agent = "research_agent.cli:main"

[tool.setuptools.packages.find]
include = ["research_agent*"]

[tool.pytest.ini_options]
testpaths = ["tests/agent"]
markers = ["real_corpus: read-only integration against the repository corpus"]
```

`.gitignore` 保留全部现有行，只追加 `/indexes/`、`/workspaces/`、`/cache/`、`/.venv/`、`/.worktrees/`、`/.pytest_cache/`、`/build/`、`/dist/`、`*.egg-info/`、`.env`、`*.local.yaml`。不添加 `*.jsonl` 或 `*.yaml` 这样的宽泛规则。

- [ ] 执行 `python -m pip install -e '.[dev]'`、同一测试和 `research-agent --version`；预期通过。
- [ ] 提交：`git add pyproject.toml .gitignore research_agent tests/agent/test_package.py && git commit -m "feat: add installable research-agent entrypoint"`。

## T2：数据契约、规范序列化与路径边界

**Files:** 创建职责图所列 schemas 与 core 基础文件；测试 `tests/agent/test_contracts.py`、`test_paths.py`。

**Interfaces:**

| 名称 | 精确契约 |
|---|---|
| `canonical_bytes(value: object) -> bytes` | sorted keys、UTF-8、无额外空格、拒绝 NaN/Infinity |
| `digest(value: object) -> str` | 规范 JSON 的 SHA-256，返回 64 位小写十六进制 |
| `safe_child(root: Path, relative: str) -> Path` | 拒绝绝对路径、空路径、`..`、反斜杠及路径中的符号链接 |
| `ArtifactRef` | `artifact_id: str`, `version: int >= 1`, `sha256: str` |
| `Claim` | `statement: str`, `epistemic_status`, `evidence_ids: tuple[str, ...]` |
| `DecisionInput` | `request_id: str`, `gate_id: str`, `artifact: ArtifactRef`, `actor: Literal['user']`, `action: Literal['approve']` |
| `GateRecord` | `gate_id`, `kind: G1/G2/G3/G4`, `artifact: ArtifactRef`, `status: pending/approved/superseded` |
| `TaskResult` | `status: completed/blocked/failed`, `outputs: tuple[ArtifactRef, ...]`, `reason: str | None`, `cache_hit: bool` |

`ResearchBrief` 保存 topic、domain、target_venue、scope、日期区间、snapshot_id、creation_basis。`WorkspaceState` 保存 workspace_id、snapshot_id、stage、status、pending_gate。领域限制在 T5 校验，不在通用 Claim 中写死医学模态。

错误统一派生 `ResearchAgentError(code, message)`：`PathViolation`、`IntegrityError`、`ConflictError`、`GateError`、`BusyError`、`UnsupportedStage`。必须让异常消息不包含密钥或完整私有内容。

- [ ] 写失败测试：

```python
import pytest
from pydantic import ValidationError
from research_agent.schemas.research import Claim
from research_agent.core.serialization import canonical_bytes, digest
from research_agent.core.paths import safe_child
from research_agent.core.errors import PathViolation


def test_fact_requires_source():
    with pytest.raises(ValidationError):
        Claim(statement="测试陈述", epistemic_status="FACT", evidence_ids=())


def test_hash_is_order_independent():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    with pytest.raises(ValueError):
        canonical_bytes({"value": float("nan")})


def test_parent_escape_rejected(tmp_path):
    with pytest.raises(PathViolation):
        safe_child(tmp_path, "../corpus/papers.jsonl")
```

- [ ] 运行 `python -m pytest tests/agent/test_contracts.py tests/agent/test_paths.py -q`，确认缺少目标实现导致失败。
- [ ] 实现基本算法并添加反斜杠、绝对路径、叶子/父目录 symlink、NaN、错误枚举、额外字段的参数化用例：

```python
import hashlib
import json


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
```

Pydantic 模型设 `extra='forbid'`。`frozen=True` 不能阻止嵌套 dict 变动，因此提交前重新规范化并计算哈希，读取时重新校验。FACT 的存在性约束由 Schema 检查；来源解析和科学支持度分别由后续存储核验及 M3 实现，不能宣称本任务已经证明事实正确。

- [ ] 同一测试通过；运行 `python -m pytest tests/agent -q` 防回归。
- [ ] 提交：`git add research_agent/schemas research_agent/core tests/agent/test_contracts.py tests/agent/test_paths.py && git commit -m "feat: define validated research contracts and safe paths"`。

## T3：读取真实 schema 的 CorpusAdapter

**Files:** 创建 `research_agent/adapters/corpus_adapter.py`、`tests/__init__.py`、`tests/agent/__init__.py`、`tests/agent/corpus_factory.py`、`tests/agent/test_corpus.py`。`CorpusVerification` 定义在 corpus_adapter.py 内。

**Interfaces:** `CorpusAdapter(repo_root: Path)`；`verify(snapshot_id: str | None = None) -> CorpusVerification`；`iter_records(snapshot_id: str) -> Iterator[dict]`。`CorpusVerification` 包含 snapshot_id、snapshot_checksum、paper_count、release_count、verified_files。

实现链路必须是 registry.snapshots → 选定 snapshot → snapshot.releases → release manifest → papers.jsonl。不得用 registry 顶层 releases 列表替代指定快照的成员。校验 JSONL 原文件应使用 `paper_shard_checksum`，不能使用含义不同的 `paper_checksum`。

- [ ] 在 corpus_factory 写一个真实哈希的小 fixture；仅存虚构书目，明确为工程测试数据：

```python
import hashlib
import json
from pathlib import Path


def make_corpus(root: Path) -> Path:
    def put(relative: str, content: bytes) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def put_json(relative: str, value: dict) -> str:
        return put(relative, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    shard = "corpus/releases/TEST/2025/release_test/papers.jsonl"
    record = {"paper_id": "fixture_p1", "canonical_title": "Fixture only",
              "paper": {"title": "Fixture only", "abstract": "a\u2028b",
                        "conference": "TEST", "year": 2025}}
    shard_hash = put(shard, (json.dumps(record, ensure_ascii=False) + "\n").encode())
    release_path = "corpus/releases/TEST/2025/release_test/manifest.json"
    release_hash = put_json(release_path, {
        "release_id": "release_test", "conference": "TEST", "year": 2025,
        "paper_count": 1, "paper_shard_path": shard,
        "paper_shard_checksum": shard_hash, "paper_checksum": "upstream-not-file-hash",
    })
    snapshot_path = "corpus/snapshots/snapshot_test/manifest.json"
    snapshot_hash = put_json(snapshot_path, {
        "snapshot_id": "snapshot_test", "paper_count": 1,
        "releases": [{"release_id": "release_test", "conference": "TEST", "year": 2025,
                      "manifest_path": release_path, "manifest_checksum": release_hash}],
    })
    put_json("corpus/registry.json", {
        "current_snapshot_id": "snapshot_test",
        "snapshots": [{"snapshot_id": "snapshot_test", "manifest_path": snapshot_path,
                       "manifest_checksum": snapshot_hash}],
    })
    return root
```

写入以下实际测试，并增加 manifest 路径越界、未知快照及读取前后文件清单不变用例：

```python
import pytest
from research_agent.adapters.corpus_adapter import CorpusAdapter
from research_agent.core.errors import IntegrityError
from tests.agent.corpus_factory import make_corpus


def test_fixture_verifies_without_splitting_unicode(tmp_path):
    repo = make_corpus(tmp_path)
    adapter = CorpusAdapter(repo)
    assert adapter.verify().paper_count == 1
    rows = list(adapter.iter_records("snapshot_test"))
    assert len(rows) == 1
    assert rows[0]["paper"]["abstract"] == "a\u2028b"


def test_changed_shard_rejected(tmp_path):
    repo = make_corpus(tmp_path)
    shard = repo / "corpus/releases/TEST/2025/release_test/papers.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    with pytest.raises(IntegrityError):
        CorpusAdapter(repo).verify()
```

- [ ] 运行 `python -m pytest tests/agent/test_corpus.py -q`，确认红灯。
- [ ] 实现只读文件哈希、引用链校验和逐行迭代：

```python
import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8", newline="\n") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                yield line_number, json.loads(line)
```

所有路径由 safe_child 限制到实际 corpus 内。除必要字段外保留上游扩展字段，不能用内部 `extra=forbid` 强制旧语料删除合法元数据。验证 release 身份/会议/年份、分片实际行数和 snapshot 总数；未知校验字段不自行解释或重写。

- [ ] fixture 全通过后增加 `@pytest.mark.real_corpus` 测试，按实际 registry 校验，不把 113989 写进通用引擎。实际仓库当前预期为 113989/86；真实校验未执行时明确 skip 原因，不把 skipped 当 PASS。
- [ ] 提交：`git add research_agent/adapters tests/agent/corpus_factory.py tests/agent/test_corpus.py && git commit -m "feat: verify and stream immutable corpus snapshots"`。

## T4：可恢复事务、Artifact 和事件存储

**Files:** 创建 `research_agent/core/store.py`、`tests/agent/test_store.py`、`tests/agent/test_recovery.py`。

**Interfaces:** `ArtifactStore(workspace_root: Path)`；`commit(artifact_id: str, version: int, payload: dict, events: list[dict], transaction_id: str) -> ArtifactRef`；`read(ref: ArtifactRef) -> dict`；`events() -> list[dict]`；`recover() -> None`。

约束：ID 只允许字母、数字、下划线和短横线；事务和 Artifact 版本不可覆盖。payload 可含 `dependencies`，每项为 ArtifactRef 字典，供 T6 使用。存储根只由 API 创建在 `repo/workspaces/<id>`；禁止传入 corpus 或受保护目录。测试直接使用 tmp_path。

- [ ] 写失败测试：

```python
import pytest
from research_agent.core.store import ArtifactStore
from research_agent.core.errors import ConflictError


def test_artifact_is_immutable_and_reopenable(tmp_path):
    store = ArtifactStore(tmp_path / "ws")
    ref = store.commit("brief", 1, {"topic": "二维生成"}, [], "tx_1")
    assert ArtifactStore(tmp_path / "ws").read(ref)["topic"] == "二维生成"
    with pytest.raises(ConflictError):
        store.commit("brief", 1, {"topic": "different"}, [], "tx_2")
```

- [ ] 运行两个测试文件并确认红灯。
- [ ] 在 Workspace 锁内实现下述提交协议。此处规定完整顺序，不能用直接覆盖 workspace.yaml 替代事务：

```text
1. 规范化 payload/events；计算哈希；检查 ID、版本和 transaction_id 冲突。
2. transaction_id 已提交且内容相同 → 返回原 ArtifactRef；内容不同 → ConflictError。
3. 将完整不可变 Artifact 写入同目录临时文件；flush + fsync。
4. 原子发布 Artifact；此时未有提交标记，下游不可见。
5. 创建 commits/<sequence>-<transaction_id>.json，包含 refs、事件、内容哈希；原子发布。
6. 提交标记为事务可见性边界；追加缺失事件至 events.jsonl 并刷新派生视图。
7. 恢复时校验有序提交标记及全部引用哈希，再补全一次且仅一次的事件。
```

原子写的基本动作如下；调用者必须已持锁并验证目标不是已有不可变版本。仅派生视图允许替换：

```python
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def publish_bytes(path: Path, content: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
```

POSIX 平台另 fsync 父目录并记录能力；不对未经验证的远程文件系统保证断电持久性。filelock 采用进程锁及有限超时，冲突映射 BusyError。用户同机单用户协作是 M1 威胁模型，不宣称抵御恶意本地进程的所有 TOCTOU 攻击。

- [ ] 用 monkeypatch 在 Artifact 发布后/提交标记前、标记后/事件追加前、事件后/投影前分别注入异常：前一种不产生已提交结果，后两种 reopen 后恢复同一事务且不重复。损坏已提交哈希必须 IntegrityError；日志中段损坏不能静默删行；尾部半行从已提交事件恢复并保留故障副本。
- [ ] 运行 `python -m pytest tests/agent/test_store.py tests/agent/test_recovery.py -q`，通过后提交：`git add research_agent/core/store.py tests/agent/test_store.py tests/agent/test_recovery.py && git commit -m "feat: persist recoverable research artifacts and events"`。

## T5：Workspace、领域配置与四个 Gate 规则

**Files:** 创建 `core/workspace.py`、`core/state_machine.py`、`core/gates.py`、`domains/medical_diffusion_2d/domain.yaml`；测试 `test_workspace.py`、`test_gates.py`。

**Interfaces:** `WorkspaceService(repo_root: Path)`；`create(topic: str, domain: str, snapshot_id: str | None = None) -> WorkspaceState`；`get_state(workspace_id: str) -> WorkspaceState`；`get_gate(workspace_id: str) -> GateRecord | None`；`approve(workspace_id: str, decision: DecisionInput) -> WorkspaceState`；`revise_brief(workspace_id: str, expected: ArtifactRef, changes: dict) -> WorkspaceState`。

- [ ] 写失败测试：

```python
import pytest
import shutil
from pathlib import Path
from research_agent.core.workspace import WorkspaceService
from research_agent.core.errors import GateError
from research_agent.schemas.workflow import DecisionInput
from tests.agent.corpus_factory import make_corpus


def test_stale_approval_cannot_advance(tmp_path):
    repo = make_corpus(tmp_path / "repo")
    relative = Path("domains/medical_diffusion_2d/domain.yaml")
    source = Path(__file__).resolve().parents[2] / relative
    destination = repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    service = WorkspaceService(repo)
    ws = service.create("二维医学图像扩散生成", "medical_diffusion_2d")
    old = service.get_gate(ws.workspace_id)
    service.revise_brief(ws.workspace_id, old.artifact, {"topic": "二维病灶条件生成"})
    with pytest.raises(GateError):
        service.approve(ws.workspace_id, DecisionInput(
            request_id="approval_1", gate_id=old.gate_id,
            artifact=old.artifact, actor="user", action="approve",
        ))
```

测试从仓库读取本任务的真实 domain.yaml 并复制到 fixture，不能访问真实 workspaces。创建 domain.yaml 后再运行行为测试，避免将缺少 fixture 配置误认成 Gate 逻辑红灯。

- [ ] 运行 `python -m pytest tests/agent/test_workspace.py tests/agent/test_gates.py -q`，确认红灯。
- [ ] 新建领域配置，至少包含以下明确值，并将合并后配置保存为不可变 Artifact；workspace.yaml 仅为可恢复投影：

```yaml
domain: medical_diffusion_2d
target_venue: MICCAI
scope:
  dimensionality: 2d
  allow_independent_ct_mri_slices: true
  allow_2_5d: false
  allow_3d: false
  primary_tasks: [generation, synthesis, local_editing, image_translation, data_augmentation]
policies:
  fulltext_mode: hybrid
  local_corpus_first: true
  external_search_allowed: true
  contribution_style: method_primary
  data_resource_levels: [L1, L2, L3]
  compute_hard_limit: null
```

通用内核不写死医学排除项；领域 validator 明确拒绝该 profile 中的 3D/2.5D 修改。配置使用安全 YAML loader，拒绝重复键、未知顶层键、非法日期和隐式字符串布尔值。日期缺省为创建日及前五年的绝对日期，闰日按目标年最后合法日期截断，存入 Brief 供 G1 修改。

Gate 转换表：G1/ResearchBrief→S2；G2/CorePaperSet→S4；G3/OpportunitySelection→S7；G4/StorySelection→S11。后面三类在 M1 只做规则单元测试，没有真实上游产物时不可开放批准路径。

approve 必须检查当前 gate、kind、ref 的版本与哈希、pending 状态、明确 user actor 和 request_id。相同 request_id/相同载荷重试返回原结果，不重复事件；相同 request_id/不同载荷冲突。不同请求重复批准已批准 gate 报 GateError。

revise_brief 按允许字段合并，重新校验，提交新版本和 supersedes；旧批准不自动沿用。G1 修改后回到 pending G1，保留历史。创建时先全量校验快照，再发布 WorkspaceCreated 和 GateOpened 事件，禁止半创建目录被列为有效课题。

- [ ] 测试有效批准、actor 非 user、错误 hash/version、重复请求、G2 跳跃、未知 domain、UTC 日期、重启后相同 Gate 和配置锁不受外部 domain 文件变化影响；预期通过。
- [ ] 提交：`git add research_agent/core/workspace.py research_agent/core/state_machine.py research_agent/core/gates.py domains tests && git commit -m "feat: enforce persistent research boundaries and user gates"`，先核对 `git diff --cached --stat` 确认没有实验/PDF 被加入。

## T6：任务指纹、已验证结果复用与依赖失效

**Files:** 创建 `core/tasks.py`、`core/dependencies.py`；测试 `test_tasks.py`、`test_dependencies.py`。

**Interfaces:** `TaskRunner(store: ArtifactStore)`；`run(operation: str, inputs: tuple[ArtifactRef, ...], profile: dict, producer: Callable[[], dict]) -> TaskResult`；`affected_artifacts(refs: dict[str, tuple[ArtifactRef, ...]], changed: ArtifactRef) -> set[str]`。

- [ ] 写失败测试：

```python
from research_agent.core.store import ArtifactStore
from research_agent.core.tasks import TaskRunner


def test_completed_task_reused_only_after_hash_check(tmp_path):
    store = ArtifactStore(tmp_path / "ws")
    calls = []

    def producer():
        calls.append(1)
        return {"value": 7}

    runner = TaskRunner(store)
    first = runner.run("fixture_probe", (), {"version": "1"}, producer)
    second = runner.run("fixture_probe", (), {"version": "1"}, producer)
    assert first.status == second.status == "completed"
    assert second.cache_hit is True
    assert len(calls) == 1
```

- [ ] 运行两个测试文件，确认红灯。
- [ ] fingerprint 使用规范 JSON 的操作名、输入 ID/版本/哈希、工作流、Schema 和 profile；明确 profile 缺省版本，不将当前时间放入可复用 fingerprint。每个尝试另有 attempt_id/time。核心计算：

```python
from research_agent.core.serialization import digest


def task_fingerprint(operation, inputs, profile):
    return digest({
        "operation": operation,
        "inputs": [ref.model_dump(mode="json") for ref in inputs],
        "profile": profile,
        "workflow_version": "m1-v1",
    })
```

运行顺序是校验输入与依赖 → 查已提交结果并验哈希 → 无缓存时记录开始 → 执行 producer → 发布结果及完成事件。producer 异常不得留下 completed；跨重启再次执行允许产生新 attempt，但只有一个已提交可见结果。M1 的 producer 仅确定性内建操作或测试函数，不执行论文里的代码。

依赖失效按 ArtifactRef 精确匹配进行 BFS，传播到所有后代；旧版本保留但标 stale，不缓存使用。循环依赖拒绝，缺失依赖阻塞。坏输出哈希报 IntegrityError，不静默重跑覆盖证据。

- [ ] 测试 profile/输入 hash 改变不命中、相同任务不同键序命中、producer 失败可重试、输出损坏拒绝、A→B→C 失效传播以及循环拒绝；预期通过。
- [ ] 提交：`git add research_agent/core/tasks.py research_agent/core/dependencies.py tests/agent/test_tasks.py tests/agent/test_dependencies.py && git commit -m "feat: add verified task reuse and dependency invalidation"`。

## T7：API/CLI 打通真实的 M1 使用流程

**Files:** 创建 `research_agent/api.py`、`research_agent/core/orchestrator.py`、`tests/agent/conftest.py`；扩展 `research_agent/cli.py` 和 `research_agent/schemas/workflow.py`；测试 `tests/agent/test_api.py`、`tests/agent/test_cli.py`。

**Interfaces:** `ResearchAgent(repo_root: Path)`，提供下列公共方法：

| 方法 | 返回 |
|---|---|
| `create_workspace(topic: str, domain: str)` | `WorkspaceState` |
| `get_status(workspace_id: str)` | `WorkspaceState` |
| `get_pending_gate(workspace_id: str)` | `GateRecord | None` |
| `approve_gate(workspace_id: str, decision: DecisionInput)` | `WorkspaceState` |
| `revise_brief(workspace_id: str, expected: ArtifactRef, changes: dict)` | `WorkspaceState` |
| `advance(workspace_id: str)` | `RunResult` |
| `validate_workspace(workspace_id: str)` | `ValidationReport` |

RunResult 和 ValidationReport 定义在 schemas/workflow.py。

RunResult 包含 `workspace_id, stage, status, reason, pending_gate, new_artifacts`；ValidationReport 包含 `valid, checked_artifacts, errors`。不暴露不存在的全文/实验 API 为成功空实现。

- [ ] 写失败测试，使用实际 fixture corpus 与复制的真实领域配置：

```python
from research_agent.api import ResearchAgent
from research_agent.schemas.workflow import DecisionInput


def test_m1_stops_honestly_at_missing_retrieval(fixture_repo):
    agent = ResearchAgent(fixture_repo)
    ws = agent.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    gate = agent.get_pending_gate(ws.workspace_id)
    assert agent.advance(ws.workspace_id).status == "waiting_for_user"
    agent.approve_gate(ws.workspace_id, DecisionInput(
        request_id="user_approval_1", gate_id=gate.gate_id,
        artifact=gate.artifact, actor="user", action="approve",
    ))
    reopened = ResearchAgent(fixture_repo)
    result = reopened.advance(ws.workspace_id)
    assert (result.stage, result.status, result.reason) == (
        "S2", "blocked", "stage_handler_not_installed",
    )
    assert result.new_artifacts == ()
```

`tests/agent/conftest.py` 的实际 fixture 定义如下，不改真实 corpus：

```python
from pathlib import Path
import shutil
import pytest
from tests.agent.corpus_factory import make_corpus


@pytest.fixture
def fixture_repo(tmp_path):
    repo = make_corpus(tmp_path / "repo")
    relative = Path("domains/medical_diffusion_2d/domain.yaml")
    source = Path(__file__).resolve().parents[2] / relative
    destination = repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return repo
```

- [ ] 运行 `python -m pytest tests/agent/test_api.py tests/agent/test_cli.py -q`，确认红灯。
- [ ] 实现 handler 注册表仅包含 S0/S1 的确定性步骤。G1 未批准时 advance 不改变状态；G1 批准后 S2 无 handler 返回上述阻塞。API 是唯一状态写入口。

CLI 新增下列实际命令，`--repo` 为必须的仓库根参数，`--json` 放在子命令前：

```text
research-agent --repo <root> --json corpus verify
research-agent --repo <root> --json workspace create --domain medical_diffusion_2d --topic <topic>
research-agent --repo <root> --json status <workspace-id>
research-agent --repo <root> --json gate show <workspace-id>
research-agent --repo <root> --json gate approve <workspace-id> --decision <decision.yaml>
research-agent --repo <root> --json gate revise <workspace-id> --revision <revision.yaml>
research-agent --repo <root> --json run <workspace-id> --until next-gate
research-agent --repo <root> --json events <workspace-id>
research-agent --repo <root> --json validate <workspace-id>
```

approval 文件字段与 DecisionInput 一致；revision 文件为 `expected: ArtifactRef` 和 `changes: dict`，只接受可修改 Brief 字段。外部文件只读，内容经安全 YAML 与 Schema 检查。

退出码统一：0=命令成功或等待 Gate；2=输入/Schema 错误；3=Gate/版本冲突；4=完整性错误；5=阶段阻塞；6=锁超时；1=未预期内部错误。JSON 模式 stdout 只输出一个对象，诊断写 stderr，不打印密钥。

- [ ] 通过 API 测试、真实子进程 CLI 测试、未批准反复 run、重启和错误输入测试；检查 API 与 CLI 结果相同。
- [ ] 提交：`git add research_agent/api.py research_agent/cli.py research_agent/core/orchestrator.py tests/agent && git commit -m "feat: expose honest M1 research workflow through API and CLI"`。

## T8：故障、只读保护、真实验收与交接

**Files:** 新增 `tests/agent/test_m1_acceptance.py`、`test_security.py`、`docs/development/m1-quickstart.md`、`requirements-dev.lock`；不修改原 `tests/conference-corpus.test.mjs`。

**Interfaces:** 只验证 T1–T7 已有公共接口，无新科研功能。

- [ ] 先写失败/边界测试：两个独立进程竞争同一 Workspace、corpus 内写入路径、symlink 越界、损坏已提交 Artifact、日志半行、过期 Gate、未知字段和私有内容泄漏。调用用户文件前确认输入源并限制写入到 Workspace。
将以下只读保护用例放入 test_m1_acceptance.py：

```python
import hashlib
from research_agent.api import ResearchAgent


def test_create_and_wait_leave_corpus_unchanged(fixture_repo):
    corpus = fixture_repo / "corpus"

    def tree_hashes():
        return {
            str(path.relative_to(corpus)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in corpus.rglob("*") if path.is_file()
        }

    before = tree_hashes()
    agent = ResearchAgent(fixture_repo)
    ws = agent.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    assert agent.advance(ws.workspace_id).status == "waiting_for_user"
    assert tree_hashes() == before
```

- [ ] 执行 `python -m pytest tests/agent/test_security.py tests/agent/test_m1_acceptance.py -q`，若失败按具体失败修正已有模块，不跳过测试、不减弱断言。
- [ ] 对真实仓库运行验收，并保存退出码和日志；用 git diff 检查受保护文件完全不变：

```bash
python -m pytest tests/agent -q -m 'not real_corpus'
python -m pytest tests/agent -q -m real_corpus
node --test tests/conference-corpus.test.mjs
python -m build
research-agent --repo . --json corpus verify
research-agent --repo . --json workspace create \
  --domain medical_diffusion_2d --topic '二维医学图像扩散生成'
git diff --exit-code 7ca629eaf843f70b319f990129121d7f0deca785 -- \
  corpus scripts DATASET_MANIFEST.json DATA_NOTICE.md tests/conference-corpus.test.mjs
```

从真实 create 输出读取 workspace_id，再运行 gate show，将其 gate_id 和 artifact 复制进明确的用户批准文件；该人工验收批准不可由生产 Orchestrator 自动生成。批准后另起进程 run，预期退出 5、S2 blocked，随后 validate 应退出 0。测试 fixture 可模拟用户请求，不能据此宣称用户批准了真实研究。

- [ ] `requirements-dev.lock` 记录实际干净虚拟环境解析的精确依赖（去掉 editable 本地路径），使用第二个新环境安装该清单并复跑测试。锁文件标明测试 Python/OS；未经测试不承诺全平台兼容。
- [ ] 快速使用文档只写已运行命令，明确未有论文检索、全文或 Idea。检查 wheel 文件列表不含 corpus、PDF、workspaces、密钥。记录真实基线测试与 agent 测试各自通过、失败、跳过数。
- [ ] 提交并交付代码分支/PR：`git add tests/agent docs/development/m1-quickstart.md requirements-dev.lock && git commit -m "test: verify M1 recovery gates and corpus immutability"`。先审阅 diff，再发 PR；不自动合并 main。

---

## 计划自审与首个代码批次

任务依赖：T1→T2→T3→T4→T5→T6→T7→T8。为减少共享状态冲突，首个代码批次顺序执行 T1–T3；完成可安装入口、Schema 和真实快照只读校验后做第一次代码检查，再进入事务与状态。不要在同一批次实现五个里程碑。

M1 完成须同时满足：可安装、真实 corpus 验证、G1 绑定版本/哈希、非法 Gate 被拒绝、独立进程恢复同一决定、任务失败不产生完成结果、依赖修改正确失效、所有运行写入限定到 Workspace、原始 corpus 测试通过、S2 缺 handler 时诚实阻塞。

## M2–M5 路线图及需要用户介入的位置

| 里程碑 | 首个可见成果 | 配置/用户介入 |
|---|---|---|
| M2 | 真正从 corpus 搜出、解释并选择论文，推进到 G2 | 此时再配置 embedding、外部搜索及筛选模型；评估小型人工标注集合 |
| M3 | 可定位全文证据卡、领域图谱、机会报告，推进到 G3 | 自动全文失败时补充少量关键论文；确认机会 |
| M4 | 迁移、非同质 Idea、最新撞车、审稿，推进到 G4 | 选择主故事与备选，不重复确认已知二维范围 |
| M5 | 完整 Story Package、实验蓝图和可用 Skill | 审阅产物质量；实验由研究者执行并回流 |

每个里程碑单独形成执行计划。M1 不提前固定尚未需要的模型供应商、PDF 库和向量服务；这些不是本计划的遗漏实现项，而是 M2/M3 明确负责的外部能力验收。

## 技术参考与核验边界

以下官方文档用于实现时查阅接口，不构成对已实现功能或最新安全版本的声明：

- Pydantic 模型与嵌套可变性：`https://docs.pydantic.dev/latest/concepts/models/`。
- Pydantic extra/config：`https://docs.pydantic.dev/latest/api/config/`。
- filelock 锁与超时：`https://py-filelock.readthedocs.io/en/latest/api.html`。
- pytest 故障注入：`https://docs.pytest.org/en/stable/how-to/monkeypatch.html`。

文档示例测试是实施指引；任何具体实现变化都应保持接口一致并先更新测试。计划完成不等于源码已存在，也不等于测试已通过。
