"""Extraction, chunking and rank fusion.

These are the parts of the original engine kept unchanged, so the tests pin the
behaviour the rest of the system relies on: page numbers that make citations
trustworthy, and an RRF implementation whose scores depend only on rank.
"""
import pytest

from backend.services.fusion_service import rrf_fusion
from backend.services.text_processor import chunk_pages, extract_pages_from_bytes

PAGES = [
    "PAGE ONE\nThe tuition fee for semester 5 is 45000 rupees.",
    "PAGE TWO\nLate payment attracts a fine of 500 rupees per week.",
    "PAGE THREE\nThe merit scholarship covers 25 percent of tuition.",
]


@pytest.fixture
def extracted(make_pdf):
    with open(make_pdf("pages.pdf", PAGES), "rb") as handle:
        return extract_pages_from_bytes(handle.read())


# ── Extraction ────────────────────────────────────────────────────────────────

def test_pages_are_extracted_individually_and_numbered_from_one(extracted):
    assert len(extracted) == 3
    assert [p["page_number"] for p in extracted] == [1, 2, 3]


def test_each_page_keeps_its_own_text(extracted):
    assert "45000" in extracted[0]["text"]
    assert "500 rupees" in extracted[1]["text"]
    assert "scholarship" in extracted[2]["text"].lower()


# ── Chunking ──────────────────────────────────────────────────────────────────

def test_chunks_carry_the_page_they_came_from(extracted):
    """This is what makes a citation's page number trustworthy."""
    chunks = chunk_pages(extracted)
    fine = [c for c in chunks if "500 rupees" in c["text"]]
    assert fine, "the fine should survive chunking"
    assert fine[0]["page_number"] == 2


def test_chunk_indexes_are_sequential_and_unique(extracted):
    chunks = chunk_pages(extracted)
    indexes = [c["chunk_index"] for c in chunks]
    assert indexes == list(range(len(chunks)))


def test_a_long_page_splits_into_several_chunks_without_losing_its_page(make_pdf):
    long_page = "\n".join(
        f"Clause {i}: candidates must submit form {i} before the stated deadline."
        for i in range(90)
    )
    with open(make_pdf("long.pdf", [long_page]), "rb") as handle:
        pages = extract_pages_from_bytes(handle.read())
    chunks = chunk_pages(pages, chunk_size=400, chunk_overlap=40)
    assert len(chunks) > 1
    assert all(c["page_number"] == 1 for c in chunks)


def test_empty_input_yields_no_chunks():
    assert chunk_pages([]) == []
    assert chunk_pages([{"page_number": 1, "text": "   "}]) == []


# ── Rank fusion ───────────────────────────────────────────────────────────────

def _hit(doc_id, score=0.5):
    return {"_id": doc_id, "_score": score, "_source": {"combined": doc_id}}


def test_rrf_uses_rank_not_score():
    """Two hits at very different similarities get the same fusion contribution."""
    strong = rrf_fusion([_hit("a", 0.99)], [])
    weak = rrf_fusion([_hit("b", 0.01)], [])
    assert strong[0]["score"] == weak[0]["score"] == pytest.approx(1 / 61)


def test_a_document_in_both_rankings_outranks_one_in_either():
    fused = rrf_fusion([_hit("both"), _hit("dense_only")], [_hit("both"), _hit("kw_only")])
    ranking = [row["source"]["combined"] for row in fused]
    assert ranking[0] == "both"
    assert fused[0]["score"] == pytest.approx(2 / 61)


def test_results_come_back_sorted(extracted):
    fused = rrf_fusion([_hit("a"), _hit("b"), _hit("c")], [_hit("c"), _hit("a")])
    scores = [row["score"] for row in fused]
    assert scores == sorted(scores, reverse=True)


def test_empty_inputs_are_safe():
    assert rrf_fusion([], []) == []
    assert len(rrf_fusion([_hit("a")], [])) == 1
    assert len(rrf_fusion([], [_hit("a")])) == 1


def test_the_ceiling_explains_the_threshold_change():
    """The best possible single-branch fusion score is 0.0164.

    Both thresholds the old code compared against (0.015 documented, 0.005 in
    code) sit below that, so any query returning even one hit passed the guard.
    """
    best_single = rrf_fusion([_hit("a")], [])[0]["score"]
    assert best_single == pytest.approx(0.01639, abs=1e-5)
    assert best_single > 0.015
    assert best_single > 0.005
