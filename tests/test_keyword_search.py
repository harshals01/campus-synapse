"""The keyword branch.

Qdrant's `MatchText` requires *every* token of the supplied text to be present in
the field. Passing a whole question therefore matches nothing, which is what the
pre-Phase-3 code did. These tests pin the replacement: strip stopwords, OR the
remaining content terms, then rank by how many of them each chunk contains.
"""
import pytest
from qdrant_client.http import models as qdrant_models

from backend.models.db_models import User
from backend.services.access_policy import allowed_document_versions
from backend.services.qdrant_service import (
    content_terms,
    doc_version_filter,
    keyword_search,
    qdrant_client,
)


def _scope(db, accounts, key):
    return allowed_document_versions(db.get(User, accounts[key]["id"]), db)


# ── content_terms ─────────────────────────────────────────────────────────────

def test_stopwords_and_punctuation_are_stripped():
    assert content_terms("What is the late payment fine?") == ["late", "payment", "fine"]


def test_duplicates_are_collapsed_and_order_is_kept():
    assert content_terms("fee fee tuition FEE") == ["fee", "tuition"]


def test_a_query_of_only_stopwords_yields_nothing():
    """The branch then skips itself instead of matching everything."""
    assert content_terms("What is it?") == []
    assert content_terms("how much do I need to") == []


def test_course_codes_survive():
    assert "cs301" in content_terms("What is the syllabus of CS301?")


@pytest.mark.parametrize(
    "query,lost",
    [
        ("What is the fee for semester 5?", "5"),
        ("attendance requirement is 70%", "70"),
        ("AI branch sem 3 timetable", "ai"),
    ],
)
def test_short_tokens_are_dropped(query, lost):
    """Documents the known trade-off rather than asserting it is desirable.

    The plan specifies stripping tokens of two characters or fewer. That loses
    semester numbers, percentages, and the branch name `AI`. The dense branch
    still carries these queries. If this is ever changed, this test should fail
    and be updated deliberately.
    """
    assert lost not in content_terms(query)


# ── keyword_search ────────────────────────────────────────────────────────────

def test_whole_question_through_match_text_finds_nothing(library, index_name):
    """The behaviour that made the old keyword branch dead code."""
    results, _ = qdrant_client.scroll(
        collection_name=index_name,
        scroll_filter=qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="combined",
                    match=qdrant_models.MatchText(text="What is the late payment fine?"),
                )
            ]
        ),
        limit=10,
    )
    assert results == []


def test_or_over_content_terms_finds_the_chunk(library, index_name, db_session, accounts):
    scope = _scope(db_session, accounts, "cse5")
    hits = keyword_search(
        index_name, "What is the late payment fine?", doc_version_filter(scope)
    )["hits"]["hits"]
    assert hits, "the rebuilt branch must find the chunk the old one missed"
    assert "500 rupees" in hits[0]["_source"]["combined"]


def test_hits_are_ranked_by_term_overlap(library, index_name, db_session, accounts):
    """A flat score would make the keyword branch's RRF rank meaningless."""
    scope = _scope(db_session, accounts, "cse5")
    hits = keyword_search(
        index_name, "late payment fine rupees week", doc_version_filter(scope)
    )["hits"]["hits"]
    scores = [h["_score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) > 1 or len(hits) == 1, "scores must discriminate, not all be 1.0"
    assert all(0 < s <= 1 for s in scores), "score is the fraction of query terms matched"


def test_an_exact_figure_is_found(library, index_name, db_session, accounts):
    """The reason hybrid search exists: dense search alone can miss exact strings."""
    scope = _scope(db_session, accounts, "cse5")
    hits = keyword_search(index_name, "45000 tuition", doc_version_filter(scope))["hits"]["hits"]
    assert any("45000" in h["_source"]["combined"] for h in hits)


def test_the_access_filter_is_respected(library, index_name, db_session, accounts):
    scope = _scope(db_session, accounts, "cse5")
    hits = keyword_search(
        index_name, "appraisal dean salary revision", doc_version_filter(scope)
    )["hits"]["hits"]
    assert all(h["_source"]["document_id"] != library["circular"] for h in hits)


def test_a_stopword_only_query_skips_the_branch(library, index_name, db_session, accounts):
    scope = _scope(db_session, accounts, "cse5")
    hits = keyword_search(index_name, "what is it", doc_version_filter(scope))["hits"]["hits"]
    assert hits == []
