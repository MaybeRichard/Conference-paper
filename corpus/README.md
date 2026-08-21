# Conference Paper Corpus

本目录是供选题流程长期复用的顶会论文元数据快照，不是论文全文库。

- 当前快照：`snapshot_a6ef56370e3258f5`
- 论文记录：113,989 条
- 发布批次：86 个
- 覆盖范围：AAAI、CVPR、ECCV、ICCV、ICLR、ICML、NeurIPS 的 2020--2026 年，
  AISTATS、IJCAI、WACV 与 MICCAI、ISBI 的 2020--2025 年，COLM 的 2024--2025 年
  （ECCV/ICCV 仅双数/单数年；各会议实际年度见 `DATASET_MANIFEST.json`）
- 核心字段：标题、摘要、作者、录用决定与层级（decision/tier）、
  轨道（track）、关键词、主研究区、GitHub/项目页链接、引用数、
  DOI、论文页面和 PDF 外部链接

`registry.json` 指向当前快照；`snapshots/` 固化快照组成；`releases/`
按会议和年份保存不可原地改写的 `manifest.json` 与 `papers.jsonl`。
仓库根目录的 `DATASET_MANIFEST.json` 给出全部 200 个数据文件的
SHA-256（含 `corpus/sources/medical/` 下 26 个已提交的 API 原始抓取
文件）；其中 `archive_root` 保留原始导出包名称，用于来源追踪。

## 数据来源

1. **原始会议导出**（2023--2026 批次）：本地导出的顶会公开元数据，
   经迁移适配器进入本结构（见各 release 的 `source_metadata.migration`）。
2. **Paper Copilot paperlists 增量导入**（2026-08-19/20）：从
   `papercopilot/paperlists`（upstream commit `9fcfd12`）按“已录用、
   2020 年起”策略导入原语料缺失的论文，覆盖 AAAI、AISTATS、COLM、
   CVPR、ECCV、ICCV、ICLR、ICML、IJCAI、NeurIPS、WACV 共 11 个会议；
   拒绝/桌面拒绝/撤回/期刊轨/空状态记录一律排除。每个新增 release 的
   `source_metadata` 固定上游 commit、文件路径与 SHA-256。后续更新：
   `git pull` 上游后运行 `python3 scripts/paperlists-import.py`
   （先 `--dry-run` 查看差量），脚本只新增 release 与快照。
3. **MICCAI 与 ISBI 官方 proceedings 导入**（2026-08-20）：医学影像两个
   主要会议 2020--2025 年全部已录用论文（4,270 + 3,123 条）。枚举以
   Crossref 出版社注册数据为准（accepted = 正式 proceedings 收录；
   MICCAI 按 LNCS 主会卷章节枚举，排除 workshop 卷；ISBI 按精确
   proceedings 标题枚举），摘要与引用数由 Semantic Scholar 批量搜索
   富集（CC BY-NC 4.0，DOI 匹配、标题回退）。API 原始抓取文件提交在
   `corpus/sources/medical/`，每个 release 的 `source_metadata` 用
   SHA-256 钉住所用文件。MICCAI 摘要覆盖率约 44--58%（LNCS 出版社
   未注册摘要且 S2 缺摘要时留空），ISBI 约 86--99%。后续更新：
   重新抓取后运行 `python3 scripts/medical-import.py --stage-from <dir>`
   再执行导入（先 `--dry-run`），脚本只新增 release 与快照。

从仓库根目录验证：

```bash
jq -r '.files[] | "\(.sha256)  \(.path)"' DATASET_MANIFEST.json | sha256sum -c -
node --test tests/conference-corpus.test.mjs
```

快速检索标题或摘要：

```bash
rg -i 'synthetic data|data augmentation' corpus/releases -g papers.jsonl
```

该快照用于建立宏观覆盖和查找全文线索，不能替代论文精读。快照未命中
也不能证明相关工作不存在；应继续检索最新会议论文、同期预印本和同义术语。
新增数据必须生成新的 release 和 snapshot，并更新 registry 与校验清单，
不得重排或改写已发布的 JSONL。来源与再分发边界见
[`DATA_NOTICE.md`](../DATA_NOTICE.md)。
