"""Retrieval must never cross the access boundary.

This is the project's central claim, so it is tested at both levels: the search
layer directly, and end to end through POST /chat.
"""
from backend.models.db_models import DocumentVersion, User
from backend.services.access_policy import allowed_document_versions
from backend.services.search_service import run_search

# Wording that appears only in the teachers-only circular.
SECRET_PHRASE = "Appraisal forms are due to the dean by 15 October"
SECRET_PARAPHRASE = "When do faculty appraisal documents have to reach the dean?"


class _Logger:
    """Collects log lines instead of writing them."""
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(message)

    warning = error = info


def _scope(db, accounts, key):
    return allowed_document_versions(db.get(User, accounts[key]["id"]), db)


def _doc_ids(hits):
    return {h["_source"].get("document_id") for h in hits}


def test_empty_scope_makes_no_query_at_all(library):
    """A user with nothing readable must not reach Qdrant, let alone Groq."""
    logger = _Logger()
    vector_hits, keyword_hits = run_search("anything at all", 10, logger, [])
    assert vector_hits == [] and keyword_hits == []
    assert any("skipping retrieval" in line for line in logger.lines)


def test_student_cannot_retrieve_a_teachers_only_document(library, db_session, accounts):
    scope = _scope(db_session, accounts, "cse5")
    for query in (SECRET_PHRASE, SECRET_PARAPHRASE, "dean appraisal salary revision"):
        vector_hits, keyword_hits = run_search(query, 20, _Logger(), scope)
        found = _doc_ids(vector_hits) | _doc_ids(keyword_hits)
        assert library["circular"] not in found, f"leaked via query: {query!r}"


def test_a_teacher_can_retrieve_that_same_document(library, db_session, accounts):
    scope = _scope(db_session, accounts, "teacher")
    vector_hits, keyword_hits = run_search(SECRET_PHRASE, 20, _Logger(), scope)
    found = _doc_ids(vector_hits) | _doc_ids(keyword_hits)
    assert library["circular"] in found, "the circular should be readable by a teacher"


def test_both_branches_carry_the_filter(library, db_session, accounts):
    """Dense and keyword search must each be scoped; neither may be a back door."""
    scope = _scope(db_session, accounts, "ece3")  # sees neither fixture document
    vector_hits, keyword_hits = run_search("fee fine rupees dean appraisal", 20, _Logger(), scope)
    allowed = set(scope)
    for hits in (vector_hits, keyword_hits):
        for hit in hits:
            assert hit["_source"]["doc_version"] in allowed


def test_unfiltered_search_would_have_leaked(library, db_session, accounts, index_name):
    """Proves the filter is doing the work, not the data being absent."""
    from backend.services.qdrant_service import semantic_search
    from conftest import stub_vector

    everything = semantic_search(index_name, stub_vector(SECRET_PHRASE), 20)["hits"]["hits"]
    assert library["circular"] in _doc_ids(everything), (
        "the circular is in the index, so the isolation tests above are meaningful"
    )


def test_chat_abstains_for_a_user_with_no_documents(ask, library, fresh_student):
    body = ask("ece3", "What is the late payment fine?", headers=fresh_student).json()
    assert body["abstained"] is True
    assert body["llm_called"] is False
    assert body["citations"] == []


def test_chat_answers_the_student_who_may_read_the_notice(ask, library):
    response = ask("cse5", "What is the late payment fine?")
    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is False
    assert body["citations"], "an answered question must cite something"
    assert library["fee"] in {c["document_id"] for c in body["citations"]}


def test_chat_never_cites_a_document_outside_the_scope(ask, library):
    body = ask("cse5", SECRET_PHRASE).json()
    cited = {c["document_id"] for c in body.get("citations", [])}
    assert library["circular"] not in cited


def test_selecting_a_forbidden_document_is_refused(ask, library):
    response = ask("cse5", "What is in this circular?", document_ids=[library["circular"]])
    assert response.status_code == 403


def test_selecting_an_allowed_document_narrows_the_scope(ask, library):
    body = ask("cse5", "What is the late payment fine?", document_ids=[library["fee"]]).json()
    assert body["abstained"] is False
    assert {c["document_id"] for c in body["citations"]} == {library["fee"]}


def test_conversation_is_owner_only(client, login, ask, library):
    conversation_id = ask("cse5", "What is the tuition fee?").json()["conversation_id"]
    assert client.get(f"/conversations/{conversation_id}", headers=login("cse5")).status_code == 200
    assert client.get(f"/conversations/{conversation_id}", headers=login("ece3")).status_code == 404
    assert client.get(f"/conversations/{conversation_id}", headers=login("admin")).status_code == 404


def test_continuing_someone_elses_conversation_is_refused(client, login, ask, library):
    conversation_id = ask("cse5", "What is the tuition fee?").json()["conversation_id"]
    response = client.post(
        "/chat",
        headers=login("ece3"),
        json={
            "messages": [{"role": "user", "content": "And the fine?"}],
            "conversation_id": conversation_id,
        },
    )
    assert response.status_code == 404


def test_history_drops_answers_whose_sources_became_unreadable(
    client, login, ask, library, db_session, accounts
):
    """An earlier answer must not be replayed to the model after access is lost."""
    from datetime import datetime, timezone

    from backend.models.db_models import Conversation, Document
    from backend.routes.chat import _history_for_llm

    first = ask("cse5", "What is the late payment fine?").json()
    conversation_id = first["conversation_id"]
    assert first["citations"]

    conversation = db_session.get(Conversation, conversation_id)
    assert _history_for_llm(
        conversation, set(_scope(db_session, accounts, "cse5")), 6
    ), "history is usable while access holds"

    document = db_session.get(Document, library["fee"])
    document.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    try:
        db_session.refresh(conversation)
        kept = _history_for_llm(conversation, set(_scope(db_session, accounts, "cse5")), 6)
        assert kept == [], "the answer and the question that produced it must both go"

        shown = client.get(f"/conversations/{conversation_id}", headers=login("cse5")).json()
        assistant = [m for m in shown["messages"] if m["role"] == "assistant"]
        assert any(
            c.get("unavailable") for m in assistant for c in (m.get("citations") or [])
        ), "the UI should be told the source is gone"
    finally:
        document.deleted_at = None
        db_session.commit()
