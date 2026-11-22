"""The access policy: who may read which document version.

`allowed_document_versions()` is the single gatekeeper every route uses, so these
tests exercise it directly as well as through GET /documents.
"""
from backend.models.db_models import Document, DocumentVersion, User
from backend.services.access_policy import allowed_document_versions


def _keys(db, user_id):
    user = db.get(User, user_id)
    return set(allowed_document_versions(user, db))


def _doc_keys(db, document_id):
    return {
        v.doc_version_key
        for v in db.query(DocumentVersion).filter(DocumentVersion.document_id == document_id)
    }


def test_class_document_reaches_only_the_matching_class(library, db_session, accounts):
    fee_keys = _doc_keys(db_session, library["fee"])
    assert fee_keys & _keys(db_session, accounts["cse5"]["id"]), "CSE sem 5 should see it"
    assert not fee_keys & _keys(db_session, accounts["ece3"]["id"]), "ECE sem 3 must not"


def test_teachers_only_document_is_hidden_from_students(library, db_session, accounts):
    circular_keys = _doc_keys(db_session, library["circular"])
    assert circular_keys & _keys(db_session, accounts["teacher"]["id"])
    assert not circular_keys & _keys(db_session, accounts["cse5"]["id"])
    assert not circular_keys & _keys(db_session, accounts["ece3"]["id"])


def test_personal_document_is_visible_only_to_its_owner(make_pdf, upload, db_session, accounts):
    response = upload("cse5", make_pdf("private_notes.pdf", ["My own revision notes about graphs."]))
    assert response.status_code == 202
    keys = _doc_keys(db_session, response.json()["document_id"])

    assert keys & _keys(db_session, accounts["cse5"]["id"])
    for other in ("ece3", "teacher", "admin"):
        assert not keys & _keys(db_session, accounts[other]["id"]), f"{other} must not see it"


def test_only_the_active_ready_version_is_allowed(library, db_session, accounts):
    """A version still processing, or superseded, is never searchable."""
    doc = db_session.get(Document, library["fee"])
    version = db_session.get(DocumentVersion, (doc.id, doc.active_version))

    version.status = "processing"
    db_session.commit()
    try:
        assert version.doc_version_key not in _keys(db_session, accounts["cse5"]["id"])
    finally:
        version.status = "ready"
        db_session.commit()

    assert version.doc_version_key in _keys(db_session, accounts["cse5"]["id"])


def test_soft_deleted_document_drops_out_immediately(library, db_session, accounts):
    from datetime import datetime, timezone

    doc = db_session.get(Document, library["fee"])
    key = db_session.get(DocumentVersion, (doc.id, doc.active_version)).doc_version_key
    assert key in _keys(db_session, accounts["cse5"]["id"])

    doc.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    try:
        assert key not in _keys(db_session, accounts["cse5"]["id"])
    finally:
        doc.deleted_at = None
        db_session.commit()


def test_audience_change_applies_without_reindexing(library, db_session, accounts):
    """Permissions live in SQLite only, never copied into the Qdrant payload."""
    doc = db_session.get(Document, library["fee"])
    key = db_session.get(DocumentVersion, (doc.id, doc.active_version)).doc_version_key
    assert key in _keys(db_session, accounts["cse5"]["id"])

    doc.audience_semester = 7  # the student is in semester 5
    db_session.commit()
    try:
        assert key not in _keys(db_session, accounts["cse5"]["id"])
    finally:
        doc.audience_semester = 5
        db_session.commit()


def test_everyone_audience_reaches_every_role(make_pdf, upload, db_session, accounts):
    response = upload(
        "admin", make_pdf("holiday_list.pdf", ["The college is closed on 2 October."]),
        audience_type="everyone",
    )
    assert response.status_code == 202
    keys = _doc_keys(db_session, response.json()["document_id"])
    for key in ("admin", "teacher", "cse5", "ece3"):
        assert keys & _keys(db_session, accounts[key]["id"]), f"{key} should see an 'everyone' doc"


def test_documents_endpoint_matches_the_policy(client, login, library):
    def listed(role):
        response = client.get("/documents", headers=login(role))
        assert response.status_code == 200
        return {d["id"] for d in response.json()}

    assert library["fee"] in listed("cse5")
    assert library["fee"] not in listed("ece3")
    assert library["circular"] in listed("teacher")
    assert library["circular"] not in listed("cse5")


def test_owner_sees_their_own_document_while_it_is_still_processing(
    library, client, login, db_session
):
    """The UI needs this to show a progress badge; others still must not see it."""
    doc = db_session.get(Document, library["fee"])
    version = db_session.get(DocumentVersion, (doc.id, doc.active_version))
    version.status = "processing"
    db_session.commit()
    try:
        own = client.get("/documents", headers=login("admin")).json()
        assert any(d["id"] == doc.id and d["active_version_status"] == "processing" for d in own)

        student = {d["id"] for d in client.get("/documents", headers=login("cse5")).json()}
        assert doc.id not in student
    finally:
        version.status = "ready"
        db_session.commit()
