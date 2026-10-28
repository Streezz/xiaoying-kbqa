import shutil
from pathlib import Path

import pytest

from kbqa.config import ROOT, load_settings
from kbqa.docstore import DocStore
from kbqa.ledger import Ledger
from kbqa.retriever import Retriever
from kbqa.tools import ToolRunner

TODAY = "2026-10-28"


@pytest.fixture(scope="session")
def settings():
    return load_settings().with_overrides(data_dir=ROOT / "data" / "docs", today=TODAY)


@pytest.fixture(scope="session")
def store():
    return DocStore(ROOT / "data" / "docs")


@pytest.fixture(scope="session")
def retriever(store):
    return Retriever(store, ROOT / "data" / "synonyms.yaml")


@pytest.fixture
def ledger():
    return Ledger()


@pytest.fixture
def runner(store, retriever, ledger):
    return ToolRunner(store, retriever, ledger, TODAY)


@pytest.fixture
def docs_copy(tmp_path):
    """可随意修改的资料副本。"""
    dst = tmp_path / "docs"
    shutil.copytree(ROOT / "data" / "docs", dst)
    return dst
