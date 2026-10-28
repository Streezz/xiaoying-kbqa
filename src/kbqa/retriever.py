"""BM25 检索 + 业务同义词归一。

检索单位是"段落"（§N）。每段的检索文本 = 文档标题 + 段落标题（算两遍，标题最能说明这段讲什么）+ 正文。
同义词在问题和文档两边都换成标准词，模型看不到这一层。

hit_quality 是给模型看的信号：BM25 分数本身对模型没有意义，
告诉它"只命中了问题里一小部分词"，它才知道该换说法再搜。
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import jieba
import yaml

from .docstore import DocStore

jieba.setLogLevel(logging.WARNING)

STOPWORDS = set(
    "的 了 吗 呢 吧 啊 呀 么 是 在 和 与 及 或 我 我们 你 你们 他 她 它 这 那 这个 那个 "
    "什么 怎么 怎么样 如何 哪些 哪个 为什么 是否 能 能不能 可以 可不可以 还 还能 要 需要 有 没有 "
    "一下 请问 一般 公司 吧 就 都 也 又 会 应 应该 想 问 请 给 让 被 把 对 从 到 于 按 后 前 内 "
    "多少 几 几天 几个 时候 一个 之后 之前 以后 上 下 完".split()
)
PUNCT_RE = re.compile(r"^[\W_]+$")

GOOD_COVERAGE = 0.6
WEAK_COVERAGE = 0.25
# 只命中一个很常见的词（如"申请"）时覆盖率也是 100%，再加一道分数门槛。
# 门槛按本项目的语料定，换语料要重看。
GOOD_MIN_SCORE = 3.0


@dataclass
class Hit:
    doc_id: str
    section_id: str
    title: str
    heading: str
    version_date: str
    preview: str
    score: float
    matched: list[str]
    coverage: float


class Retriever:
    def __init__(self, store: DocStore, synonyms_path: Path | None = None, k1: float = 1.5, b: float = 0.75):
        self.store = store
        self.k1, self.b = k1, b
        self.canon: dict[str, str] = {}
        if synonyms_path and Path(synonyms_path).exists():
            groups = yaml.safe_load(Path(synonyms_path).read_text(encoding="utf-8"))["groups"]
            for group in groups:
                for word in group:
                    self.canon[word] = group[0]
                    jieba.add_word(word, freq=20000)
        self.units = []  # (doc, section, token Counter, length)
        for doc, sec in store.all_sections():
            toks = self.tokenize(f"{doc.title} {sec.heading} {sec.heading} {sec.text}")
            self.units.append((doc, sec, Counter(toks), len(toks)))
        n = len(self.units)
        self.avgdl = sum(u[3] for u in self.units) / max(n, 1)
        df = Counter()
        for _, _, tf, _ in self.units:
            df.update(tf.keys())
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def tokenize(self, text: str) -> list[str]:
        out = []
        for tok in jieba.lcut(text):
            tok = tok.strip().lower()
            if not tok or tok in STOPWORDS or PUNCT_RE.match(tok):
                continue
            out.append(self.canon.get(tok, tok))
        return out

    def search(self, query: str, top_k: int = 5, category: str | None = None) -> tuple[list[Hit], str, list[str]]:
        q_terms = list(dict.fromkeys(self.tokenize(query)))
        if not q_terms:
            return [], "none", []
        hits = []
        for doc, sec, tf, dl in self.units:
            if category and doc.category != category:
                continue
            score, matched = 0.0, []
            for t in q_terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                matched.append(t)
                score += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if score > 0:
                hits.append(Hit(
                    doc_id=doc.doc_id, section_id=sec.section_id, title=doc.title, heading=sec.heading,
                    version_date=doc.version_date, preview=sec.text[:40] + ("…" if len(sec.text) > 40 else ""),
                    score=round(score, 3), matched=matched, coverage=round(len(matched) / len(q_terms), 2),
                ))
        hits.sort(key=lambda h: (-h.score, h.doc_id, h.section_id))
        hits = hits[:top_k]
        best = max((h.coverage for h in hits), default=0.0)
        top_score = hits[0].score if hits else 0.0
        if best >= GOOD_COVERAGE and top_score >= GOOD_MIN_SCORE:
            quality = "good"
        elif best >= WEAK_COVERAGE:
            quality = "weak"
        else:
            quality = "none"
        return hits, quality, q_terms
