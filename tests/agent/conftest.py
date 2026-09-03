from pathlib import Path
import shutil

import pytest

from tests.agent.corpus_factory import make_corpus


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    repo = make_corpus(tmp_path / "repo")
    relative = Path("domains/medical_diffusion_2d/domain.yaml")
    source = Path(__file__).resolve().parents[2] / relative
    destination = repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return repo
