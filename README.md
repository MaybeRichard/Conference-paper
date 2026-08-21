# Conference-paper：会议论文语料库（版本化、完整性可校验）

13 个机器学习 / 计算机视觉 / 医学图像会议的 **已接收（accepted-only）** 论文语料库，
覆盖 2020 年起（部分 legacy 导出更早），共 **113,989 条记录、86 个 release、
200 个数据文件**。每条记录含标题、作者、摘要（视来源）、DOI / 官方页面链接、
展示级别（oral/spotlight/poster，视来源）、引用数（视来源）等字段，
**不存储论文全文/PDF**。

当前快照：`snapshot_a6ef56370e3258f5`（见 `corpus/registry.json`）。

## 会议与规模

| 会议 | 覆盖年份 | 记录数 |
|---|---|---:|
| NeurIPS | 2020–2026* | 21,175 |
| ICML | 2020–2026* | 17,685 |
| CVPR | 2020–2026* | 17,205 |
| ICLR | 2020–2026* | 16,137 |
| AAAI | 2021–2026* | 11,900 |
| ICCV | 2021, 2023, 2025 | 6,502 |
| ECCV | 2020, 2022, 2024 | 5,391 |
| **MICCAI** | 2020–2025 | 4,270 |
| WACV | 2020–2025 | 3,604 |
| IJCAI | 2020–2024 | 3,284 |
| **ISBI** | 2020–2025 | 3,123 |
| AISTATS | 2020–2025 | 2,996 |
| COLM | 2024–2025 | 717 |

\* 2026 列为已放榜/已导出的部分批次。ECCV 仅偶数年、ICCV 仅奇数年。

## 目录结构

```
├── DATASET_MANIFEST.json        全部 200 个数据文件的 SHA-256 清单
├── DATA_NOTICE.md               数据来源与使用条款（含 S2 CC BY-NC 4.0）
├── corpus/
│   ├── registry.json            注册表 → current_snapshot_id
│   ├── releases/<会议>/<年>/release_<id>/
│   │   ├── papers.jsonl         论文记录（每行一条 JSON）
│   │   └── manifest.json        该批次的来源、排除清单、SHA-256
│   ├── snapshots/<id>/manifest.json   快照（release 组合 + 论文总数）
│   └── sources/medical/         MICCAI/ISBI 的 API 原始抓取（审计溯源）
├── scripts/
│   ├── paperlists-import.py     12 个会议的更新导入器（paperlists 上游）
│   └── medical-import.py        MICCAI/ISBI 更新导入器（Crossref+S2）
│       └── medical/             MICCAI/ISBI 抓取脚本 + 更新手册
└── tests/conference-corpus.test.mjs   语料完整性测试
```

已发布数据**不可变**：新数据只以"新 release + 新快照"进入，
不重写、不重排任何已发布的 JSONL。详见 `corpus/README.md`。

## 字段（每条记录）

恒有：`title`、`authors`、`abstract`（个别源无摘要时为空串）、`conference`、
`year`、`paper_id`、`paper_url`、`source`、`source_id`；外层另有 `aliases`、
`canonical_title`、`first_seen_year`、`ordinal`。

视来源覆盖：`track`（93.5%）、`pdf_url`（87.6%，外链不存全文）、`doi`（59.7%）、
`decision`（46.8%，有则恒为 `"accepted"`）、`citations`（40.9%，抓取时点快照）、
`tier`（40.3%，展示级别：oral/spotlight/poster/highlight/technical 等——
**所有 paperlists 导入的记录 100% 带 tier**；缺失集中在早期本地导出的记录）、
`keywords`（16%）、`primary_area`（13.4%）、`github`（6.7%）、`project`（1.5%）。

## 使用

```bash
# 全文检索
rg -i 'pixel-space diffusion' corpus/releases -g papers.jsonl

# 程序化访问
python3 - <<'EOF'
import json
reg = json.load(open('corpus/registry.json'))
snap = json.load(open(f"corpus/snapshots/{reg['current_snapshot_id']}/manifest.json"))
for rel in snap['releases']:
    path = f"corpus/releases/{rel['conference']}/{rel['year']}/{rel['release_id']}/papers.jsonl"
    ...
EOF

# 完整性校验（200 个文件）
jq -r '.files[] | "\(.sha256)  \(.path)"' DATASET_MANIFEST.json | sha256sum -c -

# 测试
node --test tests/conference-corpus.test.mjs
```

## 数据来源

1. **原始本地导出（legacy，2023–2026 批次）**：早期快照，`collection-adapter-v1` /
   `legacy-local-corpus-v1`；无公开上游，按不可变策略保留。
2. **paperlists 上游仓库**（`jzhang38-paperlists/paperlists`）：12 个会议的
   per-conference JSON（OpenReview/CVF/PMLR 等官方数据源的社区整理）；
   各 release 记录所用上游 commit 与文件 SHA-256。
3. **Crossref + Semantic Scholar**（MICCAI/ISBI 2020–2025）：Crossref 做权威
   proceedings 枚举，S2 做增强（摘要/引用数/OA PDF 链接）；原始响应提交于
   `corpus/sources/medical/`。

详细条款与许可（S2 为 CC BY-NC 4.0，非商业、需署名）见 `DATA_NOTICE.md`。

## 更新

- 12 个 paperlists 会议：上游放榜后运行 `scripts/paperlists-import.py`
  （增量导入，已存在标题自动去重；`--dry-run` 先看）。
- MICCAI/ISBI：见 `scripts/medical/README.md`（Crossref 枚举 + S2 增强 +
  `medical-import.py --stage-from`）。
- 任何更新都会产生新 release + 新快照，随后需更新 `DATASET_MANIFEST.json`、
  测试常量与本 README 的统计，并重新跑完整性校验。

## 已知限制

- 不含拒稿/撤稿记录（accepted-only；各 release 的排除清单见其
  `manifest.json → source_metadata.excluded`）。
- 摘要覆盖：ISBI 86–99%，MICCAI 44–58%（LNCS 出版商注册摘要缺失），
  其余会议 95%+；个别记录摘要为空串。
- 引用数为抓取时点快照，不随时间更新。
- 不存储论文全文/PDF（仅外部链接）。
- 早期本地导出批次无展示级别（tier）信息，属上游数据本身缺失。
