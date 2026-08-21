import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const sha256 = (path) =>
  createHash("sha256").update(readFileSync(path)).digest("hex");

const inventory = readJson("DATASET_MANIFEST.json");
const registry = readJson("corpus/registry.json");

test("checksum-addressed corpus inventory is intact", () => {
  assert.equal(inventory.snapshot_id, registry.current_snapshot_id);
  assert.equal(inventory.paper_count, 113989);
  assert.equal(inventory.release_count, 86);
  assert.equal(inventory.files.length, 200);

  for (const entry of inventory.files) {
    assert.equal(sha256(entry.path), entry.sha256, entry.path);
  }
});

test("registry, snapshot, releases, and JSONL counts agree", () => {
  const snapshotEntry = registry.snapshots.find(
    ({ snapshot_id }) => snapshot_id === registry.current_snapshot_id,
  );
  assert.ok(snapshotEntry, "current snapshot is missing from registry");
  assert.equal(
    sha256(snapshotEntry.manifest_path),
    snapshotEntry.manifest_checksum,
  );

  const snapshot = readJson(snapshotEntry.manifest_path);
  assert.equal(snapshot.snapshot_id, registry.current_snapshot_id);
  assert.equal(snapshot.releases.length, inventory.release_count);

  let total = 0;
  for (const releaseEntry of snapshot.releases) {
    assert.equal(
      sha256(releaseEntry.manifest_path),
      releaseEntry.manifest_checksum,
      releaseEntry.manifest_path,
    );

    const release = readJson(releaseEntry.manifest_path);
    assert.equal(release.release_id, releaseEntry.release_id);
    assert.equal(release.conference, releaseEntry.conference);
    assert.equal(release.year, releaseEntry.year);

    const rows = readFileSync(release.paper_shard_path, "utf8")
      .split("\n")
      .filter(Boolean);
    assert.equal(rows.length, release.paper_count, release.paper_shard_path);
    for (const row of rows) JSON.parse(row);
    total += rows.length;
  }

  assert.equal(total, snapshot.paper_count);
  assert.equal(total, inventory.paper_count);
});
