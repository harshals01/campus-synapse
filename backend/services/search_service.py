"""
Retrieval — dense and keyword search, both scoped to the caller's allowed document versions.

Every search carries the same `doc_version` filter, built from
`access_policy.allowed_document_versions()`. There is deliberately no fallback
that widens the scope: a caller with nothing readable gets no Qdrant call at all,
and a search that finds nothing returns nothing rather than retrying unfiltered.
"""
from backend.config import INDEX_NAME
from backend.services.embedding_service import get_embedding
from backend.services.qdrant_service import (
    doc_version_filter,
    keyword_search,
    semantic_search,
)


def run_search(
    query: str,
    top_k: int,
    logger,
    allowed_versions: list[str],
) -> tuple[list[dict], list[dict]]:
    """Run both retrieval branches inside the caller's permitted scope.

    Returns ``(vector_hits, keyword_hits)``. Both branches receive the identical
    access filter, so neither can surface a chunk the caller may not read.
    """
    if not allowed_versions:
        logger.info("[SEARCH] Caller has no readable document versions — skipping retrieval.")
        return [], []

    logger.info(f"[SEARCH] Scope: {len(allowed_versions)} document version(s).")
    access_filter = doc_version_filter(allowed_versions)

    query_vector = get_embedding(query)
    vector_hits = semantic_search(
        INDEX_NAME, query_vector, top_k, query_filter=access_filter
    )["hits"]["hits"]

    # Runs on every query now. The old `extract_entity` gate meant exact-term
    # searches only happened for questions starting with "what is", "explain" and
    # similar; the branch returns empty on its own when a query has no content words.
    keyword_hits = keyword_search(
        INDEX_NAME, query, query_filter=access_filter
    )["hits"]["hits"]

    logger.info(
        f"[SEARCH] {len(vector_hits)} dense hit(s), {len(keyword_hits)} keyword hit(s)."
    )
    return vector_hits, keyword_hits
