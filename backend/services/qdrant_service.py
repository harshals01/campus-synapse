import os

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from backend import config
from backend.logger import get_logger

logger = get_logger()

if config.QDRANT_URL == ":memory:":
    qdrant_client = QdrantClient(":memory:")
    logger.info("Qdrant client initialized — in-memory mode (data is not persisted).")
elif config.QDRANT_URL:
    _client_kwargs: dict = {"url": config.QDRANT_URL}
    if config.QDRANT_API_KEY:
        _client_kwargs["api_key"] = config.QDRANT_API_KEY
    qdrant_client = QdrantClient(**_client_kwargs)
    logger.info(f"Qdrant client initialized — remote URL: {config.QDRANT_URL}")
else:
    # Local-file mode: no server to run, data persists under QDRANT_PATH.
    # Only one process may hold this path open, hence uvicorn --workers 1.
    os.makedirs(config.QDRANT_PATH, exist_ok=True)
    qdrant_client = QdrantClient(path=config.QDRANT_PATH)
    logger.info(f"Qdrant client initialized — local-file mode at '{config.QDRANT_PATH}'.")


def ensure_collection_exists(collection_name: str) -> None:
    """Create the Qdrant collection and payload indexes if they do not already exist."""
    try:
        qdrant_client.get_collection(collection_name)
        logger.info(f"Collection '{collection_name}' is ready.")
    except Exception:
        logger.info(f"Collection '{collection_name}' not found. Creating...")
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=qdrant_models.VectorParams(
                size=384,
                distance=qdrant_models.Distance.COSINE,
            ),
        )
        logger.info(f"Collection '{collection_name}' created successfully.")

    # `doc_version` is the single key every access filter is built on.
    # NOTE: payload indexes have no effect in local-file mode (filters still
    # return correct results, just unindexed). A remote Qdrant server requires
    # the text index on 'combined' before MatchText will match anything.
    payload_indexes = [
        ("combined", qdrant_models.TextIndexParams(type="text", tokenizer=qdrant_models.TokenizerType.WORD, lowercase=True)),
        ("doc_version", qdrant_models.KeywordIndexParams(type="keyword")),
    ]
    for field_name, schema in payload_indexes:
        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema,
            )
        except Exception:
            pass


try:
    ensure_collection_exists(config.INDEX_NAME)
except Exception as _e:
    logger.warning(
        f"Qdrant startup check failed: {_e}. "
        "Verify QDRANT_URL / QDRANT_PATH are correctly set."
    )


# ── Access filter helper ──────────────────────────────────────────────────────

def doc_version_filter(allowed_versions: list[str]) -> qdrant_models.Filter:
    """Build the filter that restricts a search to the document versions a caller may read.

    Callers must never pass an empty list — short-circuit before searching
    instead, so no Qdrant round-trip happens for a user with no readable documents.
    """
    return qdrant_models.Filter(
        must=[
            qdrant_models.FieldCondition(
                key="doc_version",
                match=qdrant_models.MatchAny(any=allowed_versions),
            )
        ]
    )


# ── Search ────────────────────────────────────────────────────────────────────

def semantic_search(
    collection_name: str,
    query_vector: list,
    top_k: int,
    query_filter: qdrant_models.Filter | None = None,
) -> dict:
    """Return top-K documents ranked by cosine similarity to the query vector."""
    try:
        results = qdrant_client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )
        hits = [
            {"_id": str(p.id), "_score": p.score, "_source": p.payload}
            for p in results.points
        ]
        return {"hits": {"hits": hits}}
    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        return {"hits": {"hits": []}}


# Common English question words carry no retrieval signal and, because Qdrant's
# MatchText requires every token of a phrase to be present, leaving them in makes
# the keyword branch match nothing at all.
_STOPWORDS = {
    "about", "after", "all", "also", "and", "any", "are", "been", "before", "being",
    "but", "can", "did", "does", "doing", "done", "for", "from", "get", "give", "had",
    "has", "have", "her", "him", "his", "how", "into", "its", "just", "know", "like",
    "many", "may", "me", "much", "must", "my", "need", "not", "now", "off", "once",
    "one", "only", "onto", "our", "out", "over", "please", "same", "she", "should",
    "some", "such", "tell", "than", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "those", "through", "told", "too", "under", "until",
    "upon", "use", "very", "was", "way", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your",
}


def content_terms(query: str) -> list[str]:
    """Reduce a question to its distinct content words, lowercased.

    Punctuation is dropped, stopwords and tokens of two characters or fewer are
    removed, and order is preserved. Returns an empty list when nothing survives.
    """
    cleaned = "".join(
        ch.lower() if (ch.isalnum() or ch.isspace()) else " " for ch in query
    )
    terms: list[str] = []
    seen: set[str] = set()
    for word in cleaned.split():
        if len(word) <= 2 or word in _STOPWORDS or word in seen:
            continue
        seen.add(word)
        terms.append(word)
    return terms


def keyword_search(
    collection_name: str,
    query: str,
    query_filter: qdrant_models.Filter | None = None,
) -> dict:
    """Return documents containing any content word of the query.

    Qdrant's MatchText requires *every* token of the supplied text to be present
    in the field, so passing a whole question matches nothing. Each content word
    therefore becomes its own `should` clause (OR), while the access filter stays
    in `must`. Results are scored by the fraction of query terms a chunk contains,
    because `scroll` returns rows in arbitrary order and a flat score would make
    the keyword branch's fusion rank meaningless.
    """
    terms = content_terms(query)
    if not terms:
        logger.info("[KEYWORD] No content terms in query; skipping keyword branch.")
        return {"hits": {"hits": []}}

    try:
        should = [
            qdrant_models.FieldCondition(
                key="combined",
                match=qdrant_models.MatchText(text=term),
            )
            for term in terms
        ]
        must = list(query_filter.must or []) if query_filter is not None else []
        combined_filter = qdrant_models.Filter(must=must or None, should=should)

        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=combined_filter,
            limit=100,
            with_payload=True,
            with_vectors=False,
        )

        hits = []
        for p in results:
            payload = p.payload or {}
            text = (payload.get("combined") or "").lower()
            matched = sum(1 for term in terms if term in text)
            if matched == 0:
                continue
            hits.append(
                {
                    "_id": str(p.id),
                    "_score": matched / len(terms),
                    "_source": payload,
                }
            )
        hits.sort(key=lambda h: h["_score"], reverse=True)
        return {"hits": {"hits": hits}}
    except Exception as e:
        logger.error(f"Keyword search failed: {e}")
        return {"hits": {"hits": []}}


# ── Deletion ──────────────────────────────────────────────────────────────────

def delete_points_by_doc_version(collection_name: str, doc_version: str) -> int:
    """Delete every chunk belonging to one document version.

    Returns the number of points removed, measured as a collection count
    difference, so the figure is approximate under concurrent writes.
    """
    try:
        before = qdrant_client.count(collection_name=collection_name).count
        qdrant_client.delete(
            collection_name=collection_name,
            points_selector=qdrant_models.FilterSelector(
                filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="doc_version",
                            match=qdrant_models.MatchValue(value=doc_version),
                        )
                    ]
                )
            ),
        )
        after = qdrant_client.count(collection_name=collection_name).count
        removed = before - after
        logger.info(f"[QDRANT] Removed {removed} points for doc_version '{doc_version}'.")
        return removed
    except Exception as e:
        logger.error(f"delete_points_by_doc_version failed for '{doc_version}': {e}")
        return 0
