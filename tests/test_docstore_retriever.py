import pytest

from kbqa.docstore import DocStore, DocStoreError
from kbqa.faults import FaultPlan


def test_load_all_docs(store):
    assert len(store.docs) == 11
    assert list(store.get("D01").sections) == ["§1", "§2", "§3", "§4", "§5"]
    assert "30天内" in store.section("D01", "§3").text


def test_status_on_today(store):
    assert store.get("D04").status_on("2026-10-28") == "废止"
    assert store.get("D06").status_on("2026-10-28") == "待生效"
    assert store.get("D06").status_on("2027-01-01") == "现行"
    assert store.get("D04").superseded_by == "D01"


def test_hash_changes_with_content(docs_copy):
    before = DocStore(docs_copy).section("D02", "§3").hash
    f = next(docs_copy.glob("D02_*.md"))
    f.write_text(f.read_text(encoding="utf-8").replace("15日", "20日"), encoding="utf-8")
    assert DocStore(docs_copy).section("D02", "§3").hash != before


def test_duplicate_doc_id_rejected(docs_copy):
    src = next(docs_copy.glob("D01_*.md"))
    (docs_copy / "D01_copy.md").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(DocStoreError, match="重复"):
        DocStore(docs_copy)


def test_synonyms_normalized(retriever):
    assert retriever.tokenize("报账") == retriever.tokenize("报销")
    assert "期限" in retriever.tokenize("多久")


def test_search_reimbursement_deadline(retriever):
    hits, quality, _ = retriever.search("报销期限多久？")
    keys = {f"{h.doc_id}{h.section_id}" for h in hits}
    assert quality == "good"
    assert {"D01§3", "D02§3"} <= keys


def test_colloquial_question_still_hits_reimbursement(retriever):
    hits, quality, _ = retriever.search("钱垫付了多久之内要交单？")
    assert quality == "weak"  # 只命中部分词，提示模型换说法
    assert any(h.doc_id in ("D01", "D02") for h in hits)


def test_out_of_scope_has_no_good_hit(retriever):
    assert retriever.search("公司年终奖什么时候发？")[1] == "none"
    assert retriever.search("劳动法规定年假最少几天？")[1] != "good"


def test_generic_single_word_is_weak(retriever):
    assert retriever.search("那个怎么申请？")[1] == "weak"


def test_fault_plan_parsing():
    fp = FaultPlan("search:timeout@1,2; read:not_found@D02")
    assert fp.check("search_docs", {"query": "x"}) == "TIMEOUT"
    assert fp.check("search_docs", {"query": "x"}) == "TIMEOUT"
    assert fp.check("search_docs", {"query": "x"}) is None
    assert fp.check("read_section", {"doc_id": "D01", "section_id": "§3"}) is None
    assert fp.check("read_section", {"doc_id": "D02", "section_id": "§3"}) == "NOT_FOUND"
    assert FaultPlan("info:error@*").check("get_doc_info", {"doc_ids": ["D01"]}) == "TOOL_ERROR"
    with pytest.raises(ValueError):
        FaultPlan("search-timeout")
