from kbqa import gate
from kbqa.faults import FaultPlan
from kbqa.tools import SubmitArgs

TODAY = "2026-10-28"
D01_Q = "员工原则上应在费用发生后30天内提交报销申请；因特殊情况无法按期提交的，经分管领导书面批准，可延长至60天。"
D02_Q = "员工应于费用发生之日起15日内完成报销申请。"


def read(runner, doc, sec):
    res, _ = runner.run("read_section", {"doc_id": doc, "section_id": sec, "reason": "t"}, 1)
    assert res.ok, res.error_msg
    return res


def submit(**kw):
    base = {"status": "ANSWERED", "answer": "a", "citations": [], "doc_verdicts": []}
    base.update(kw)
    return SubmitArgs(**base)


def check(sub, runner, store, warned=None):
    return gate.check(sub, runner.ledger, store, TODAY, runner.had_error, warned if warned is not None else set())


# ---------- 工具 ----------

def test_read_records_ledger_and_normalizes_section(runner):
    res, args = runner.run("read_section", {"doc_id": "D01", "section_id": "3"}, 1)
    assert res.ok and args["section_id"] == "§3"
    assert runner.ledger.get("D01", "§3") is not None
    assert runner.ledger.read_this_turn == {"D01"}


def test_read_missing_section_lists_toc(runner):
    res, _ = runner.run("read_section", {"doc_id": "D01", "section_id": "§9"}, 1)
    assert not res.ok and res.error_code == "NOT_FOUND" and "§3 报销期限" in res.error_msg


def test_bad_args_returned_not_raised(runner):
    res, _ = runner.run("search_docs", "{not json", 1)
    assert res.error_code == "BAD_ARGS"
    res, _ = runner.run("search_docs", {"query": ""}, 1)
    assert res.error_code == "BAD_ARGS"
    assert not runner.had_error  # 参数错误不算工具故障


def test_duplicate_call_cached_then_blocked(runner):
    a = {"query": "报销期限"}
    r1, _ = runner.run("search_docs", a, 1)
    r2, _ = runner.run("search_docs", {**a, "reason": "不同的 reason 不影响判重"}, 2)
    r3, _ = runner.run("search_docs", a, 3)
    assert r1.ok and r2.ok and "重复调用" in r2.note and r2.attempts == 0
    assert r3.error_code == "DUPLICATE_CALL"


def test_timeout_retried_once_by_program(runner):
    runner.faults = FaultPlan("search:timeout@1")
    res, _ = runner.run("search_docs", {"query": "年假"}, 1)
    assert res.ok and res.attempts == 2


def test_timeout_twice_reaches_model(runner):
    runner.faults = FaultPlan("search:timeout@1,2")
    res, _ = runner.run("search_docs", {"query": "年假"}, 1)
    assert res.error_code == "TIMEOUT" and runner.had_error
    res, _ = runner.run("search_docs", {"query": "年假"}, 2)  # 失败的调用不进缓存，再调会真正执行
    assert res.ok


def test_doc_info_marks_ledger(runner):
    res, _ = runner.run("get_doc_info", {"doc_ids": ["D01", "D06", "X9"]}, 1)
    docs = {d["doc_id"]: d for d in res.data["docs"]}
    assert docs["D06"]["status"] == "待生效" and docs["X9"]["error"] == "NOT_FOUND"
    assert set(runner.ledger.info_checked) == {"D01", "D06"}


# ---------- 核验规则 ----------

def test_rule1_unread_citation_rejected(runner, store):
    runner.run("search_docs", {"query": "报销期限"}, 1)  # 只搜不读
    g = check(submit(citations=[{"doc_id": "D02", "section_id": "§3", "quote": D02_Q}],
                     doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}]), runner, store)
    assert not g.passed and any("没有读过原文" in p for p in g.problems)


def test_rule2_quote_must_match(runner, store):
    read(runner, "D02", "§3")
    g = check(submit(citations=[{"doc_id": "D02", "section_id": "§3", "quote": "15个工作日内报销"}],
                     doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}]), runner, store)
    assert any("对不上" in p for p in g.problems)


def test_rule2_quote_whitespace_tolerated_and_expanded(runner, store):
    read(runner, "D02", "§3")
    g = check(submit(citations=[{"doc_id": "D02", "section_id": "§3", "quote": "15日内 完成报销申请"}],
                     doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}]), runner, store)
    assert g.passed, g.problems
    assert g.final["citations"][0]["quote"] == D02_Q


def test_rule2_truncated_qualifier_warned_once(runner, store):
    read(runner, "D01", "§3")
    sub = submit(answer="最长30天", citations=[{"doc_id": "D01", "section_id": "§3", "quote": "在费用发生后30天内提交报销申请"}],
                 doc_verdicts=[{"doc_id": "D01", "verdict": "basis"}])
    warned = set()
    g1 = check(sub, runner, store, warned)
    assert not g1.passed and any("截断" in p and "原则上" in p for p in g1.problems)
    g2 = check(sub, runner, store, warned)  # 同一段只提示一次
    assert g2.passed and g2.final["citations"][0]["quote"] == D01_Q


def test_rule3_stale_evidence_rejected(runner, store, docs_copy):
    from kbqa.docstore import DocStore

    read(runner, "D02", "§3")
    f = next(docs_copy.glob("D02_*.md"))
    f.write_text(f.read_text(encoding="utf-8").replace("15日", "30日"), encoding="utf-8")
    new_store = DocStore(docs_copy)
    g = gate.check(submit(citations=[{"doc_id": "D02", "section_id": "§3", "quote": D02_Q}],
                          doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}]),
                   runner.ledger, new_store, TODAY, False, set())
    assert any("已更新" in p for p in g.problems)
    assert runner.ledger.drop_stale(new_store) == ["D02§3"]


def test_rule4_every_read_doc_needs_verdict(runner, store):
    read(runner, "D01", "§3")
    read(runner, "D02", "§3")
    g = check(submit(citations=[{"doc_id": "D01", "section_id": "§3", "quote": D01_Q}],
                     doc_verdicts=[{"doc_id": "D01", "verdict": "basis"}]), runner, store)
    assert any(p.startswith("D02") and "表态" in p for p in g.problems)


def test_rule4_abolished_and_future_docs_cannot_be_basis(runner, store):
    read(runner, "D04", "§2")
    read(runner, "D06", "§2")
    g = check(submit(citations=[{"doc_id": "D04", "section_id": "§2", "quote": "员工应在费用发生后45天内提交报销申请。"},
                                {"doc_id": "D06", "section_id": "§2", "quote": "已满1年不满10年的，年休假7天"}],
                     doc_verdicts=[{"doc_id": "D04", "verdict": "basis"}, {"doc_id": "D06", "verdict": "basis"}]),
              runner, store)
    assert any("D04 已废止" in p for p in g.problems)
    assert any("D06 自 2027-01-01" in p for p in g.problems)


def test_rule5_conflict_requires_both_read_and_info(runner, store):
    read(runner, "D01", "§3")
    sub = submit(status="NEED_CONFIRMATION", clarify_question="以哪份为准？",
                 citations=[{"doc_id": "D01", "section_id": "§3", "quote": D01_Q}],
                 conflicts=[{"topic": "报销期限", "positions": [
                     {"doc_id": "D01", "section_id": "§3", "claim": "30天"},
                     {"doc_id": "D02", "section_id": "§3", "claim": "15日"}]}],
                 doc_verdicts=[{"doc_id": "D01", "verdict": "conflict"}])
    g = check(sub, runner, store)
    assert any("D02§3 没有读过原文" in p for p in g.problems)
    assert any("get_doc_info" in p for p in g.problems)

    read(runner, "D02", "§3")
    runner.run("get_doc_info", {"doc_ids": ["D01", "D02"]}, 2)
    sub.doc_verdicts.append(type(sub.doc_verdicts[0])(doc_id="D02", verdict="conflict"))
    sub.citations.append(type(sub.citations[0])(doc_id="D02", section_id="§3", quote=D02_Q))
    assert check(sub, runner, store).passed


def test_rule6_status_field_consistency(runner, store):
    assert not check(submit(status="NEED_CONFIRMATION"), runner, store).passed
    assert not check(submit(status="NEED_CLARIFICATION"), runner, store).passed
    g = check(submit(status="NO_EVIDENCE", answer="一般是12月发，按3个月工资", gaps=["无年终奖制度"]), runner, store)
    assert any("具体规定" in p for p in g.problems)
    assert check(submit(status="NO_EVIDENCE", answer="资料中没有年终奖的规定，建议咨询人力资源部。",
                        gaps=["无年终奖制度"]), runner, store).passed
    g = check(submit(status="FAILED", answer="失败"), runner, store)
    assert any("不能用 FAILED" in p for p in g.problems)


def test_unverified_doc_blocks_answered(runner, store):
    """C08 第一次录制暴露的问题：冲突一方读不到时，模型把它标成 not_applicable，以 ANSWERED 结束。"""
    runner.faults = FaultPlan("read:not_found@D02")
    read(runner, "D01", "§3")
    res, _ = runner.run("read_section", {"doc_id": "D02", "section_id": "§3"}, 1)
    assert not res.ok and runner.failed_reads == {"D02"}
    sub = submit(citations=[{"doc_id": "D01", "section_id": "§3", "quote": D01_Q}],
                 doc_verdicts=[{"doc_id": "D01", "verdict": "basis"},
                               {"doc_id": "D02", "verdict": "not_applicable", "reason": "读取失败"}])
    g = gate.check(sub, runner.ledger, store, TODAY, runner.had_error, set(), runner.failed_reads)
    assert any("未能核实" in p for p in g.problems)
    failed = submit(status="FAILED", answer="D02 读取失败，无法确认是否冲突。", gaps=["D02§3 未能读取"],
                    citations=[{"doc_id": "D01", "section_id": "§3", "quote": D01_Q}],
                    doc_verdicts=[{"doc_id": "D01", "verdict": "not_applicable", "reason": "冲突未核实"},
                                  {"doc_id": "D02", "verdict": "not_applicable", "reason": "读取失败"}])
    assert gate.check(failed, runner.ledger, store, TODAY, runner.had_error, set(), runner.failed_reads).passed


def test_failed_read_then_success_is_verified(runner, store):
    res, _ = runner.run("read_section", {"doc_id": "D02", "section_id": "§9"}, 1)  # 段落编号猜错
    read(runner, "D02", "§3")
    sub = submit(citations=[{"doc_id": "D02", "section_id": "§3", "quote": D02_Q}],
                 doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}])
    assert gate.check(sub, runner.ledger, store, TODAY, runner.had_error, set(), runner.failed_reads).passed
