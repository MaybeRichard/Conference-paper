# 原始来源数据（corpus/sources）

本目录保存**本项目直接抓取**的 API 原始响应，用于逐 release 审计溯源
（每个 release 的 `manifest.json → source_metadata.files` 用 SHA-256 钉住对应文件）。

## 为什么只有 `medical/`？

各会议数据的"原始层"所在位置不同：

| 数据层 | 会议 | 原始数据位置 |
|---|---|---|
| `sources/medical/`（本目录，26 文件） | MICCAI 2020–2025、ISBI 2020–2025 | Crossref + Semantic Scholar 原始响应，**本项目抓取，随仓库提交** |
| paperlists 上游仓库 | ICML、CVPR、ICCV、NeurIPS、ICLR、AAAI、IJCAI、ECCV、AISTATS、WACV、COLM 的 paperlists 批次 | 外部仓库 `jzhang38-paperlists/paperlists` 的 per-conference JSON（上游持续维护；各 release 的 `source_metadata` 记录所用上游 commit 与文件 SHA-256） |
| 原始本地导出（legacy） | 2023–2026 已导出批次（`collection-adapter-v1` / `legacy-local-corpus-v1`） | 早期本地快照，无公开上游；按不可变策略保留，不重写、不重排 |

MICCAI/ISBI 没有现成的上游聚合仓库，所以原始抓取必须随仓库保存，
否则这两个会议的 7,393 条记录无法复现。

## 布局

```
medical/
├── source-info.json        staging 元数据（API、方法、抓取时间、许可）
├── crossref/
│   ├── miccai-<year>.json  按 LNCS 主会卷聚合的章节列表（2020–2025）
│   └── isbi-<year>.json    按年度 proceedings 的 Crossref message（2020–2025）
└── s2/
    ├── miccai-<year>.json  Semantic Scholar bulk search（含 2026 预抓）
    └── isbi-<year>.json
```

更新流程见 `../../scripts/medical/README.md`。
