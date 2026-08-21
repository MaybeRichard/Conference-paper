# MICCAI / ISBI 更新工具

MICCAI 与 ISBI 的数据管线（与其他 12 个会议不同）：

1. **Crossref**（权威枚举）："accepted = 收录于官方 proceedings"，出版商注册即为准。
2. **Semantic Scholar**（仅增强）：摘要、引用数、开放获取 PDF 链接；不可用于枚举。

## 脚本

| 脚本 | 作用 | 输出（raw 布局） |
|---|---|---|
| `fetch_crossref.py --miccai-volume <book_doi>` | 抓取一个 MICCAI LNCS 主会卷的全部章节 | `<out>/vols/<book_doi 中 /→_>.json` |
| `fetch_crossref.py --isbi <year> "<container-title>"` | 抓取一个 ISBI 年度 proceedings | `<out>/isbi_xref_<year>.json` |
| `fetch_s2.py --venue <MICCAI\|ISBI> --year <year>` | 抓取 S2 增强数据 | `<out>/<venue>_<year>.json` |
| `../medical-import.py --stage-from <out>` | 校验 + 归档 raw 数据并导入语料 | 新 release + 新快照 |

## 新增一个 MICCAI 年度（例如 2026）

1. 在 Springer 的 MICCAI 2026 proceedings 页面收集**主会卷**的 book DOI
   （`10.1007/978-...` 形式）。Workshop 卷可以不抓，抓取了也会在 staging 时
   被自动剔除（标题须含 ` – MICCAI ` 且不含 `Workshop`）。
2. 逐卷运行：
   ```bash
   python3 scripts/medical/fetch_crossref.py --out RAW --miccai-volume 10.1007/978-3-031-XXXXX-X
   ```
3. 运行 `python3 scripts/medical/fetch_s2.py --out RAW --venue MICCAI --year 2026`。
4. 扩展 `scripts/medical-import.py` 中的常量：`YEARS["MICCAI"]` 与 `S2_FILES["MICCAI"]`
   加入 2026（stage() 内 ISBI 的 `range(...)` 同理）。
5. 试跑 + 正式导入：
   ```bash
   python3 scripts/medical-import.py --dry-run --stage-from RAW
   python3 scripts/medical-import.py --stage-from RAW
   ```
6. 重新生成/核对 `DATASET_MANIFEST.json`（见根 README「完整性校验」），
   跑测试，更新 README 统计与 `corpus/README.md`。

## 新增一个 ISBI 年度（例如 2026）

1. 找到该年度 proceedings 的**精确** `container-title`（IEEE/Crossref 注册名）。
   注意坑：**序数词可能缺失**——2024 的注册标题是
   `2024 IEEE International Symposium on Biomedical Imaging (ISBI)`（没有 `21st`）。
   猜错会返回 0 条（脚本会显式报错）。
2. ```bash
   python3 scripts/medical/fetch_crossref.py --out RAW --isbi 2026 "2026 IEEE 23rd International Symposium on Biomedical Imaging (ISBI)"
   ```
3. `python3 scripts/medical/fetch_s2.py --out RAW --venue ISBI --year 2026`
4. 扩展 `medical-import.py`：`YEARS["ISBI"]`、`S2_FILES["ISBI"]`、stage() 中 ISBI 的年份 `range`。
5. `--dry-run` 后正式导入，校验并更新文档。

## 已知限制

- MICCAI 摘要覆盖较低（LNCS 出版商注册摘要缺失 + S2 缺口），增强尽力而为。
- S2 未认证请求限速严重，大年度抓取可能耗时较长（429 自动退避）。
- S2 数据许可 CC BY-NC 4.0（非商业、需署名），见 `DATA_NOTICE.md`。
