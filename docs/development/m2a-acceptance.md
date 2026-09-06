# M2A acceptance and review notes

Scope: standalone local lexical retrieval, not complete S2/S3, G2, online enrichment or an end-to-end research Agent.
Base: M1 `3c712fb722ca9fc2268a88eebd9f6a14e8a898f1`. All changes belong to the separate `feat/research-agent-m2a-lexical` branch.

## Local evidence, 2026-09-06 (Singapore date)

The development container could not resolve GitHub. Instead, GitHub Actions archived the committed source tree only; the connector returned the ZIP. Its digest was verified (`dd009f2425f2f997cb91c421d199584953f59a93c8adcfeac98cb29929ba1c46`), and the extracted Git tree matched `373e09a2800aa48e5c3fdae27afe86e3e764b17a` at bootstrap commit `a58490f8c0fd54911f230aa64c7d34dae2a75b43`. Development used a new local worktree, never the user's existing modified checkout.

- Baseline: original Node tests 2 passed; original Python suite 190 passed.
- M1 + M2A: 240 passed, including 50 new tests.
- Installed wheel, outside the source-package directory: 240 passed; import asserted the wheel environment's site-packages path. Local test dependencies were shared from the preinstalled environment because network installation was unavailable. This is not a fresh dependency-resolution test.
- Local CPython 3.13.5, SQLite 3.46.1, Node 22.16.0.
- compileall and git diff --check passed.
- Local sdist and wheel built through the installed setuptools backend without build isolation; the CI workflow separately uses `python -m build` and a fresh wheel environment.
- Original corpus/scripts/manifests/Node test unchanged relative to the source baseline.

## Red/green evidence

New index, query and report tests were run before those modules existed. An initial context-manager test was corrected to actually enter the connection context; that correction was a test defect, not a production bug.

Further tests exposed and fixed:

1. The outer canonical ID and nested source paper ID must both be retained; the original implementation stored only the outer ID. Added source_paper_id and source_title, advanced normalization profile to source-text-v2.
2. A non-boolean `report="false"` could cause an unintended report write. Public API now rejects it before searching or creating report files.
3. Missing FTS5 at read time was incorrectly classified as corrupt index. It now returns typed fts5_unavailable / exit 5.
4. The expanded CLI description must preserve the existing M1 command-surface contract. Existing tests remain unmodified.

One long real-corpus smoke invocation exceeded the execution tool's timeout after publishing the complete index; the next invocation reused and verified that index and completed. No partially built index was reported as ready.

## Real pinned snapshot

- snapshot: snapshot_a6ef56370e3258f5
- source hash: ee7d5a78248419e8cb31a4070b4430e3a492c565418e21766bef7b870ea2391e
- 113,989 source records, 86 releases, 173 manifest-chain files.
- 2,276 missing/placeholder abstracts, matching the user's diagnostic under the adopted field definition.
- Query: 二维医学图像扩散生成; limit 50; per-channel cap 500.
- Bounded union: 506 records; returned: 50; enrichment queue: 29.
- RetiDiff, DiDGen and DiffStain appear despite missing abstracts; both canonical and source IDs retained.
- This is an engineering calibration against known papers, not measured semantic precision, recall@K, verified 2D eligibility or novelty.

## CI evidence contract

`.github/workflows/m2a-lexical.yml` runs CPython 3.12 / Node 24 on Ubuntu and macOS 14, the complete test suite, original corpus tests, isolated source/wheel build, wheel-content audit, real-corpus smoke, isolated installed-wheel tests, protected-assets diff and clean-checkout check.

Check the exact PR head's Actions result rather than transferring an old green result to a new commit. CI artifacts include smoke-summary.json, index-manifest.json, source-commit.txt, return_bundle.zip and the wheel. They do not include the raw corpus, private Workspace, full abstracts or model secrets.

## Remaining boundaries

- Curated bilingual glossary, not general translation or LLM query understanding.
- Field counts and lexical mentions, not bibliographic correctness or semantic inclusion/exclusion decisions.
- Missing-abstract queue, not downloaded/enriched abstracts.
- Filesystem checks assume a trusted single-user checkout and reject static symlinks; not an OS sandbox against hostile concurrent path replacement.
- Database checksum verifies the specific built index; bit-identical rebuilds across SQLite versions are not promised.
- Internal review only; no independent reviewer or GitHub approval is claimed.
- The 190 M1 tests remain intact and `run` continues to stop at S2 until a genuine workflow stage is installed.
