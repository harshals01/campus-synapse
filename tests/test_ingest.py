"""Upload: audience rules, limits, point IDs, and background indexing."""
import uuid

from backend import config
from backend.models.db_models import Document, DocumentVersion
from backend.routes.ingest import point_id


def test_background_indexing_reaches_ready_with_real_page_numbers(library, db_session):
    version = db_session.get(DocumentVersion, (library["fee"], 1))
    assert version.status == "ready", version.error
    assert version.page_count == 3, "the fixture PDF has three pages"
    assert version.chunk_count and version.chunk_count > 0
    assert version.error is None

    doc = db_session.get(Document, library["fee"])
    assert doc.active_version == 1, "active_version is published in the same commit as 'ready'"


def test_non_pdf_is_rejected(client, login, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a pdf")
    with open(path, "rb") as handle:
        response = client.post(
            "/ingest",
            headers=login("cse5"),
            files={"file": ("notes.txt", handle, "text/plain")},
        )
    assert response.status_code == 400


def test_empty_file_is_rejected(client, login):
    response = client.post(
        "/ingest",
        headers=login("cse5"),
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_oversized_file_is_rejected(client, login):
    oversized = b"%PDF-1.4\n" + b"0" * (config.MAX_FILE_SIZE_BYTES + 1)
    response = client.post(
        "/ingest",
        headers=login("cse5"),
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert response.status_code == 413


def test_image_only_pdf_fails_with_a_clear_reason(client, login, tmp_path):
    """No OCR, so a PDF with no text layer must fail loudly rather than index nothing."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "scanned.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.rect(100, 100, 200, 200, fill=1)  # a filled box, no text
    pdf.showPage()
    pdf.save()

    with open(path, "rb") as handle:
        response = client.post(
            "/ingest",
            headers=login("cse5"),
            files={"file": ("scanned.pdf", handle, "application/pdf")},
        )
    assert response.status_code == 202, "the upload itself succeeds; indexing then fails"

    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        version = db.get(DocumentVersion, (response.json()["document_id"], 1))
        assert version.status == "failed"
        assert "text" in (version.error or "").lower()
    finally:
        db.close()


def test_student_cannot_share_with_anyone(upload, make_pdf):
    path = make_pdf("attempt.pdf", ["Trying to publish college-wide."])
    for audience in ("everyone", "students", "teachers", "class"):
        response = upload("cse5", path, audience_type=audience, audience_branch="CSE")
        assert response.status_code == 403, f"student should not reach audience={audience}"


def test_teacher_can_only_share_with_a_class(upload, make_pdf):
    path = make_pdf("course_notes.pdf", ["Unit 1 covers sorting and searching."])
    for audience in ("everyone", "students", "teachers"):
        assert upload("teacher", path, audience_type=audience).status_code == 403
    assert upload("teacher", path, audience_type="class").status_code == 202


def test_teachers_branch_is_forced_to_their_own(upload, make_pdf, db_session):
    """A CSE teacher naming ECE must still publish to CSE."""
    response = upload(
        "teacher", make_pdf("lab_manual.pdf", ["Lab 1: install the toolchain."]),
        audience_type="class", audience_branch="ECE", audience_semester="3",
    )
    assert response.status_code == 202
    doc = db_session.get(Document, response.json()["document_id"])
    assert doc.audience_branch == "CSE"
    assert doc.audience_semester == 3, "semester may narrow, branch may not move"


def test_admin_may_target_any_branch(upload, make_pdf, db_session):
    response = upload(
        "admin", make_pdf("ece_notice.pdf", ["ECE sem 3 lab timings have changed."]),
        audience_type="class", audience_branch="ECE", audience_semester="3",
    )
    assert response.status_code == 202
    assert db_session.get(Document, response.json()["document_id"]).audience_branch == "ECE"


def test_class_audience_requires_a_branch_from_an_admin(upload, make_pdf):
    response = upload("admin", make_pdf("x.pdf", ["Body."]), audience_type="class")
    assert response.status_code == 400


def test_invalid_audience_values_are_rejected(upload, make_pdf):
    path = make_pdf("y.pdf", ["Body."])
    assert upload("admin", path, audience_type="nonsense").status_code == 400
    assert upload("admin", path, audience_type="class", audience_branch="XYZ").status_code == 400
    assert upload("admin", path, audience_type="class", audience_branch="CSE",
                  audience_semester="99").status_code == 400


def test_default_upload_is_personal(upload, make_pdf, db_session):
    response = upload("cse5", make_pdf("mine.pdf", ["Personal notes."]))
    assert response.status_code == 202
    doc = db_session.get(Document, response.json()["document_id"])
    assert doc.category == "personal"
    assert doc.audience_type is None


def test_same_filename_from_two_users_stays_separate(upload, make_pdf, db_session):
    """The old filename-derived point IDs collided here; version-scoped ones do not."""
    alice = upload("cse5", make_pdf("report.pdf", ["Alice's own report about queues."]))
    bob = upload("ece3", make_pdf("report.pdf", ["Bob's own report about filters."]))
    assert alice.status_code == bob.status_code == 202

    a_id, b_id = alice.json()["document_id"], bob.json()["document_id"]
    assert a_id != b_id
    a_doc, b_doc = db_session.get(Document, a_id), db_session.get(Document, b_id)
    assert a_doc.display_name == b_doc.display_name == "report.pdf"
    assert a_doc.owner_id != b_doc.owner_id


def test_point_ids_are_deterministic_and_version_scoped():
    """Re-indexing overwrites its own points; other versions and documents never collide."""
    assert point_id("doc-a", 1, 0) == point_id("doc-a", 1, 0)
    assert point_id("doc-a", 1, 0) != point_id("doc-a", 2, 0)
    assert point_id("doc-a", 1, 0) != point_id("doc-b", 1, 0)
    assert point_id("doc-a", 1, 0) != point_id("doc-a", 1, 1)
    uuid.UUID(point_id("doc-a", 1, 0))  # must be a valid UUID for Qdrant


def test_per_user_document_quota_is_enforced(upload, make_pdf, monkeypatch, client, login):
    monkeypatch.setattr(config, "MAX_FILES_PER_USER", 1)
    path = make_pdf("quota.pdf", ["Quota test body text."])
    first = upload("ece3", path)
    second = upload("ece3", path)
    # ece3 may already own documents from other tests, so accept either ordering.
    assert 400 in (first.status_code, second.status_code)


def test_upload_requires_authentication(client, make_pdf):
    with open(make_pdf("anon.pdf", ["Body."]), "rb") as handle:
        response = client.post(
            "/ingest", files={"file": ("anon.pdf", handle, "application/pdf")}
        )
    assert response.status_code in (401, 403)


def test_delete_removes_the_document_and_its_chunks(client, login, upload, make_pdf, index_name):
    from backend.services.qdrant_service import qdrant_client

    response = upload("cse5", make_pdf("temp.pdf", ["Disposable content about trees."]))
    document_id = response.json()["document_id"]
    before = qdrant_client.count(collection_name=index_name).count

    deleted = client.delete(f"/documents/{document_id}", headers=login("cse5"))
    assert deleted.status_code == 200
    assert deleted.json()["deleted_chunks"] > 0
    assert qdrant_client.count(collection_name=index_name).count < before

    listed = {d["id"] for d in client.get("/documents", headers=login("cse5")).json()}
    assert document_id not in listed


def test_cannot_delete_someone_elses_document(client, login, library):
    """A document that exists but is not yours is indistinguishable from one that doesn't."""
    response = client.delete(f"/documents/{library['fee']}", headers=login("cse5"))
    assert response.status_code == 404
