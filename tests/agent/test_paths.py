"""Paths are checked under a trusted local root; this is not an OS sandbox."""
import pytest


def test_valid_child_is_returned_without_creating_files(tmp_path):
    from research_agent.core.paths import safe_child
    assert safe_child(tmp_path, "papers/p1.json") == tmp_path / "papers/p1.json"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("relative", ["", ".", "..", "../corpus/x", "x/../y", "/tmp/x",
    "C:/outside", "C:relative", "a\\b", "a\x00b", "//host/x", "x/./y", "a//b"])
def test_unsafe_paths_rejected(tmp_path, relative):
    from research_agent.core.paths import safe_child
    from research_agent.core.errors import PathViolation
    with pytest.raises(PathViolation):
        safe_child(tmp_path, relative)


@pytest.mark.parametrize("target_exists", [True, False])
def test_leaf_symlink_rejected_even_if_dangling(tmp_path, target_exists):
    from research_agent.core.paths import safe_child
    from research_agent.core.errors import PathViolation
    target = tmp_path / "target"
    if target_exists:
        target.write_text("private")
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(PathViolation):
        safe_child(tmp_path, "link")


def test_parent_symlink_rejected_even_if_target_is_inside_root(tmp_path):
    from research_agent.core.paths import safe_child
    from research_agent.core.errors import PathViolation
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(PathViolation):
        safe_child(tmp_path, "link/file.json")


def test_symlink_root_rejected(tmp_path):
    from research_agent.core.paths import safe_child
    from research_agent.core.errors import PathViolation
    (tmp_path / "real").mkdir()
    (tmp_path / "root").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(PathViolation):
        safe_child(tmp_path / "root", "file.json")


def test_regular_file_cannot_be_a_parent(tmp_path):
    from research_agent.core.paths import safe_child
    from research_agent.core.errors import PathViolation
    (tmp_path / "file").write_text("x")
    with pytest.raises(PathViolation):
        safe_child(tmp_path, "file/child")


def test_relative_path_not_leaked_in_error(tmp_path):
    from research_agent.core.paths import safe_child
    from research_agent.core.errors import PathViolation
    with pytest.raises(PathViolation) as error:
        safe_child(tmp_path, "../secret_access_token")
    assert "secret_access_token" not in str(error.value)
