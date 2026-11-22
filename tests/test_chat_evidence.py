"""Abstention, citations and persistence.

The evidence check runs on the top dense cosine similarity, not on the RRF score.
An RRF score depends only on rank, so a single first-ranked hit always scores
1/(60+1) ≈ 0.0164 however poor the match — above both thresholds the old code
compared against, which is why it could effectively never abstain.
"""
from backend import config
from backend.models.db_models import Message, QueryLog
from backend.services.fusion_service import rrf_fusion


def test_answered_question_reports_both_signals_separately(ask, library):
    body = ask("cse5", "What is the late payment fine?").json()
    assert body["abstained"] is False
    assert body["llm_called"] is True
    assert body["hits_used"] > 0
    assert body["top_similarity"] > config.SIMILARITY_THRESHOLD
    assert body["top_fusion_score"] > 0
    assert body["top_similarity"] != body["top_fusion_score"], (
        "these are different measurements and must not be conflated"
    )


def test_fusion_score_alone_cannot_separate_good_from_bad(library):
    """Why the evidence signal had to change."""
    one_hit = rrf_fusion([{"_id": "x", "_score": 0.01, "_source": {}}], [])
    assert round(one_hit[0]["score"], 4) == round(1 / 61, 4) == 0.0164
    # A barely-relevant single hit still clears the old thresholds.
    assert one_hit[0]["score"] > 0.015, "README default would not have blocked it"
    assert one_hit[0]["score"] > 0.005, "code default would not have blocked it"


def test_off_topic_question_abstains(ask, library):
    body = ask("cse5", "Explain the quantum chromodynamics lagrangian in detail").json()
    assert body["abstained"] is True
    assert body["llm_called"] is False, "no Groq call should be made when abstaining"
    assert body["citations"] == []
    assert body["top_similarity"] < config.SIMILARITY_THRESHOLD


def test_citations_point_at_the_right_page(ask, library):
    """The fine is on page 2 of the fixture PDF."""
    body = ask("cse5", "What is the late payment fine?").json()
    pages = [c["page_number"] for c in body["citations"]]
    assert 2 in pages, f"expected page 2 among {pages}"


def test_citations_carry_what_the_ui_needs(ask, library):
    citation = ask("cse5", "What is the tuition fee for semester 5?").json()["citations"][0]
    for field in ("id", "document_id", "version", "display_name", "page_number", "snippet", "score"):
        assert field in citation, f"missing {field}"
    assert citation["display_name"] == "fee_notice.pdf"
    assert citation["snippet"]


def test_a_conversation_id_is_always_returned(ask, library):
    for question in ("What is the tuition fee?", "Explain quantum chromodynamics"):
        assert ask("cse5", question).json()["conversation_id"]


def test_turns_are_persisted(ask, library, db_session):
    conversation_id = ask("cse5", "What is the merit scholarship worth?").json()["conversation_id"]
    messages = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "What is the merit scholarship worth?"


def test_stored_citations_hold_references_not_snippets(ask, library, db_session):
    """So content removed later cannot reappear out of the message table."""
    conversation_id = ask("cse5", "What is the late payment fine?").json()["conversation_id"]
    assistant = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.role == "assistant")
        .first()
    )
    assert assistant.citations
    stored = assistant.citations[0]
    assert set(stored) == {"document_id", "version", "page_number", "chunk_index"}
    assert "snippet" not in stored


def test_abstentions_are_logged_as_unanswered(ask, library, db_session, accounts):
    before = db_session.query(QueryLog).filter(QueryLog.answered == False).count()  # noqa: E712
    ask("cse5", "What is the airspeed velocity of an unladen swallow?")
    db_session.expire_all()
    after = db_session.query(QueryLog).filter(QueryLog.answered == False).count()  # noqa: E712
    assert after == before + 1, "the admin dashboard depends on this"


def test_answered_questions_are_logged_with_their_sources(ask, library, db_session):
    question = "What is the tuition fee for semester 5 please?"
    ask("cse5", question)
    db_session.expire_all()
    row = (
        db_session.query(QueryLog)
        .filter(QueryLog.question == question)
        .order_by(QueryLog.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.answered is True
    assert row.abstained is False
    assert library["fee"] in row.cited_documents


def test_question_log_is_visible_to_an_admin(client, login, ask, library):
    ask("cse5", "What is the late payment fine?")
    everything = client.get("/admin/questions", headers=login("admin"))
    assert everything.status_code == 200
    assert len(everything.json()) > 0

    unanswered = client.get("/admin/questions?answered=false", headers=login("admin"))
    assert unanswered.status_code == 200
    assert all(row["answered"] is False for row in unanswered.json())


def test_changing_document_scope_starts_a_new_conversation(client, login, ask, library):
    """Otherwise one thread would mix evidence from two different scopes."""
    first = ask("cse5", "What is the tuition fee?").json()["conversation_id"]
    second = client.post(
        "/chat",
        headers=login("cse5"),
        json={
            "messages": [{"role": "user", "content": "And the fine?"}],
            "conversation_id": first,
            "document_ids": [library["fee"]],
        },
    ).json()["conversation_id"]
    assert second != first


def test_empty_question_is_rejected(client, login):
    response = client.post(
        "/chat",
        headers=login("cse5"),
        json={"messages": [{"role": "user", "content": "   "}]},
    )
    assert response.status_code == 400


def test_prompt_labels_retrieved_text_as_untrusted(ask, library, monkeypatch):
    """A PDF must not be able to issue instructions to the model."""
    captured = {}

    import backend.routes.chat as chat_module

    def spy(payload, logger):
        captured["system"] = payload["messages"][0]["content"]
        return "ok [1]"

    monkeypatch.setattr(chat_module, "call_llm", spy)
    ask("cse5", "What is the late payment fine?")

    system = captured["system"]
    assert "<context>" in system and "</context>" in system
    assert "untrusted" in system.lower()
    assert "500 rupees" in system, "the retrieved chunk should be inside the delimiters"
