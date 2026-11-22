"""PDF preview links.

A signed link is a convenience, never the authority. `GET /files/{token}` must
re-check the account and the current access policy on every request, so a link
that was valid a moment ago stops working the instant access changes.
"""
from backend.auth import create_preview_token
from backend.models.db_models import Document, User


def _mint(client, login, role, document_id, page=None):
    return client.post(
        f"/documents/{document_id}/preview-link",
        headers=login(role),
        params={"page": page} if page else {},
    )


def test_an_allowed_user_can_mint_a_token_and_fetch_the_pdf(client, login, library):
    minted = _mint(client, login, "cse5", library["fee"], page=2)
    assert minted.status_code == 200
    body = minted.json()
    assert body["page_fragment"] == "#page=2"

    served = client.get(f"/files/{body['token']}")
    assert served.status_code == 200
    assert "no-store" in served.headers.get("cache-control", "")
    assert served.headers.get("referrer-policy") == "no-referrer"


def test_no_page_means_no_fragment(client, login, library):
    assert _mint(client, login, "cse5", library["fee"]).json()["page_fragment"] == ""


def test_a_user_outside_the_audience_cannot_mint_one(client, login, library):
    assert _mint(client, login, "ece3", library["fee"]).status_code in (403, 404)
    assert _mint(client, login, "cse5", library["circular"]).status_code in (403, 404)


def test_minting_requires_authentication(client, library):
    assert client.post(f"/documents/{library['fee']}/preview-link").status_code in (401, 403)


def test_an_unknown_document_is_a_404(client, login):
    assert _mint(client, login, "cse5", "no-such-document").status_code == 404


def test_a_forged_token_is_refused(client):
    assert client.get("/files/not-a-real-token").status_code == 403


def test_a_token_minted_for_another_user_does_not_work(client, accounts, library):
    """The token is bound to a user, so it cannot be passed around."""
    token = create_preview_token(accounts["ece3"]["id"], library["fee"], 1)
    assert client.get(f"/files/{token}").status_code == 403


def test_a_token_for_a_document_the_holder_cannot_read_is_refused(client, accounts, library):
    token = create_preview_token(accounts["cse5"]["id"], library["circular"], 1)
    assert client.get(f"/files/{token}").status_code == 403


def test_an_expired_token_is_refused(client, login, library, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import jwt

    from backend import config

    expired = jwt.encode(
        {
            "sub": "irrelevant",
            "aud": "preview",
            "document_id": library["fee"],
            "version": 1,
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        config.JWT_SECRET,
        algorithm="HS256",
    )
    assert client.get(f"/files/{expired}").status_code == 403


def test_deactivation_kills_a_token_that_has_not_expired(
    client, login, library, db_session, accounts
):
    token = _mint(client, login, "cse5", library["fee"]).json()["token"]
    assert client.get(f"/files/{token}").status_code == 200

    user = db_session.get(User, accounts["cse5"]["id"])
    user.active = False
    db_session.commit()
    try:
        assert client.get(f"/files/{token}").status_code == 403
    finally:
        user.active = True
        db_session.commit()

    assert client.get(f"/files/{token}").status_code == 200, "and works again once restored"


def test_an_audience_change_kills_a_token_that_has_not_expired(
    client, login, library, db_session
):
    token = _mint(client, login, "cse5", library["fee"]).json()["token"]
    assert client.get(f"/files/{token}").status_code == 200

    document = db_session.get(Document, library["fee"])
    document.audience_semester = 7  # the student is in semester 5
    db_session.commit()
    try:
        assert client.get(f"/files/{token}").status_code == 403
    finally:
        document.audience_semester = 5
        db_session.commit()


def test_deleting_the_document_kills_a_token_that_has_not_expired(
    client, login, library, db_session
):
    from datetime import datetime, timezone

    token = _mint(client, login, "cse5", library["fee"]).json()["token"]
    document = db_session.get(Document, library["fee"])
    document.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    try:
        assert client.get(f"/files/{token}").status_code == 403
    finally:
        document.deleted_at = None
        db_session.commit()


def test_a_document_still_processing_cannot_be_previewed(client, login, upload, make_pdf, db_session):
    from backend.models.db_models import DocumentVersion

    document_id = upload("cse5", make_pdf("pending.pdf", ["Body text here."])).json()["document_id"]
    version = db_session.get(DocumentVersion, (document_id, 1))
    version.status = "processing"
    db_session.commit()
    try:
        assert _mint(client, login, "cse5", document_id).status_code == 409
    finally:
        version.status = "ready"
        db_session.commit()
