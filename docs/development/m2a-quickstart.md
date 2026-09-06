# M2A：实际可用的本地论文候选检索

本批是 M2 的第一片，不是完整 S2/G2。M1 的审批、恢复与 `run` 行为不变；本批的 `search` 单独读取固定索引，不推进课题。无需 GPU、模型密钥或联网服务；安装 Python 依赖时仍需可用包源。

## 使用前

分支：`feat/research-agent-m2a-lexical`，依赖尚未合并的 `feat/research-agent-m1`。
不要把 M2A 合并到 M1，也不要为试用执行 reset/restore/clean。
本地若有原始 corpus 的未提交修改，应使用新 worktree/clone，**不要修复或覆盖原工作区来让检查通过**。

例如已有完整 Git 仓库时，在仓库外创建新 worktree：

```bash
REPO="/你的绝对路径/Conference-paper"
git -C "$REPO" fetch origin feat/research-agent-m2a-lexical
M2A_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/research-m2a.XXXXXX")"
git -C "$REPO" worktree add --detach "$M2A_ROOT/repo" origin/feat/research-agent-m2a-lexical
cd "$M2A_ROOT/repo"
git rev-parse HEAD
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Python >=3.11，SQLite 需含 FTS5。缺 FTS5 时明确返回 `fts5_unavailable`，不会静默伪造语义检索。
临时目录可能被系统清理；长期使用请把 `M2A_ROOT` 换成自己创建的固定外部目录。不要把既有研究 Workspace 复制到测试目录。

## 只需试用这些新命令

```bash
python -m research_agent --repo "$PWD" --json index status
python -m research_agent --repo "$PWD" --json index build > /tmp/m2a-index.json
python -m research_agent --repo "$PWD" --json index verify
python -m research_agent --repo "$PWD" --json search \
  --query "二维医学图像扩散生成" --limit 50 --report > /tmp/m2a-search.json
python - <<'PY'
import json
from pathlib import Path
r = json.loads(Path('/tmp/m2a-search.json').read_text(encoding='utf-8'))
print('返回候选:', len(r['candidates']))
print('缺摘要补全队列:', len(r['missing_abstract_queue']))
print('报告:', r['report']['report_path'])
print('只需回传这个文件:', r['report']['bundle_path'])
PY
```

`index build` 完成全部原始校验和流式读取后才发布索引。相同快照/profile 可以复用，数据库损坏则明确拒绝，不自动覆盖。
`index verify` 重验源语料；`search` 验证冻结索引，**不每次重新读取源语料**。修改后的源文件不会静默被带入已发布索引。

不要把示例路径 `/tmp/m2a-search.json` 放进生产自动化共用目录。自动化应使用各运行独有目录；生成的报告目录本身使用随机 ID，不覆盖旧报告。

## 定向查询与过滤

```bash
python -m research_agent --repo "$PWD" --json search --query "RetiDiff" --report
python -m research_agent --repo "$PWD" --json search --query "diffusion retinal synthesis" --year-from 2023 --year-to 2025 --report
python -m research_agent --repo "$PWD" --json search --query "diffusion virtual staining" --conference MICCAI --report
```

检索是纯文本，不支持用户直接传 SQL 或 FTS 运算符。少量中文概念采用公开可审计的字典展开，不是任意中文翻译。未知中文修饰词和否定条件报输入错误；请使用明确英文词组合，或检查报告中的查询计划。

`--per-channel` 默认500，上限5000；`--limit` 默认50，上限1000。会议/年份过滤在每路截断前执行。无年份过滤时搜索整个指定快照，不冒称仅近五年；需要时间窗请显式传年份参数。

## 如何读报告

- `paper_id` 是外层语料规范记录标识；`source_paper_id` 是来源记录内部 ID，可能分别是 `paper_...` 与 `papermed_...`，不是换了一篇论文。
- 标题、摘要与联合通道的 BM25 排名经 RRF 融合；分数不是相关性/录用概率。
- 缺摘要的标题命中有独立保留名额，不把无摘要当作不相关。标为 `missing_abstract_reserved`。
- `2d_mentioned`、`3d_mentioned`、`segmentation_mentioned` 等只是词面提示，所有候选仍是 `scope_status=unreviewed`。二维骨干不证明任务独立二维。
- “候选报告”是可供人工筛查的检索结果，不是用户已批准的 G2。真正的语义筛选、代表性选择与精读留待下一批。
- `missing_abstract_queue.jsonl` 只覆盖本次有界召回的缺摘要记录，`enrichment_status=not_attempted`，**不是已补齐摘要**。
- 匹配数、截断和覆盖都记录；未计算真实 Recall@K，不据此声称全领域覆盖或研究空白。
- 报告含查询文本与论文元数据，提交前可检查内容。回传ZIP不含完整摘要、原始JSONL、PDF、数据库、Workspace或环境变量。

## 需要回传什么

正常试用只回传命令打印的 `return_bundle.zip`，并说明前10篇有没有明显相关/明显不相关的论文。无需再复制190项M1测试。
失败时保留实际退出码和JSON错误，回传失败命令及输出；不要改原始语料、manifest或测试断言。

| 退出码 | 含义 |
|---|---|
| 0 | 命令完成；可能真实零命中，不等于无人研究 |
| 2 | 查询/参数不支持或输入无效 |
| 3 | 索引发布冲突 |
| 4 | 索引、来源或路径完整性错误 |
| 5 | 索引未建立 / SQLite缺FTS5；`run`仍可能因未安装S2处理器返回5 |
| 6 | 另一个索引构建占用锁 |

## 开发验收（用户正常试用不用全跑）

```bash
node --test tests/conference-corpus.test.mjs
python -m pytest tests/agent -q -ra
python -m compileall -q research_agent
python -m build
OUT="$(mktemp -d "${TMPDIR:-/tmp}/m2a-evidence.XXXXXX")"
python tools/m2a_smoke.py --repo "$PWD" --out "$OUT"
git diff --check
git status --short
```

该 smoke 使用固定语料的已知标题做工程召回校准；不评价整套检索的科学质量。独立代码审查和真实研究者相关性评测仍需另行完成。
