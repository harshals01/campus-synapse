"""
Generate synthetic BIT Mesra documents for demos and evaluation, and optionally
upload them with the right audience.

These are invented, not real college documents, so they are safe to show and safe
to send to Groq. Replace them with real PDFs when you have them — the audience
plan below is what matters, not the text.

    python -m scripts.make_demo_pdfs --out data/demo_pdfs
    python -m scripts.make_demo_pdfs --out data/demo_pdfs --upload \
        --base-url http://127.0.0.1:8000 \
        --admin admin@bitmesra.ac.in --password admin123
"""
import argparse
import os
import sys

DOCUMENTS = [
    {
        "filename": "fee_notice_cse_sem5.pdf",
        "audience": {"audience_type": "class", "audience_branch": "CSE", "audience_semester": 5},
        "pages": [
            """SEMESTER 5 FEE NOTICE - CSE - SESSION 2026-27
            Birla Institute of Technology, Mesra

            The tuition fee for semester 5 of the B.Tech CSE programme is
            62500 rupees. The last date for payment without a fine is
            30 September 2026.

            Payment is accepted online through the student portal or by
            demand draft at the accounts office between 10:00 and 16:00
            on working days.""",
            """LATE PAYMENT AND CONSEQUENCES

            Fees paid after 30 September 2026 attract a late fine of
            500 rupees per week, calculated from the due date and capped
            at 5000 rupees in total.

            Hall tickets for the end-semester examination are withheld
            until all dues, including any late fine, are cleared. A student
            with outstanding dues on the date of the examination will not be
            permitted to appear.""",
            """REFUND POLICY

            A student who withdraws from the programme is refunded on the
            following scale: 90 percent of tuition if written notice reaches
            the registrar before 15 August 2026, 50 percent if it reaches
            before 30 August 2026, and no refund after that date.

            The one-time admission fee is never refundable. Hostel and mess
            charges are governed by a separate notice from the warden.""",
        ],
    },
    {
        "filename": "fee_notice_ece_sem3.pdf",
        "audience": {"audience_type": "class", "audience_branch": "ECE", "audience_semester": 3},
        "pages": [
            """SEMESTER 3 FEE NOTICE - ECE - SESSION 2026-27

            The tuition fee for semester 3 of the B.Tech ECE programme is
            58000 rupees, payable on or before 30 September 2026.

            The laboratory deposit of 2000 rupees is collected once in
            semester 3 and is refundable at the end of the programme.""",
            """LATE PAYMENT - ECE

            A late fine of 500 rupees per week applies after the due date,
            capped at 5000 rupees. Students with dues outstanding will not
            receive their hall tickets.""",
        ],
    },
    {
        "filename": "exam_timetable_cse_sem5.pdf",
        "audience": {"audience_type": "class", "audience_branch": "CSE", "audience_semester": 5},
        "pages": [
            """END SEMESTER EXAMINATION TIMETABLE
            CSE SEMESTER 5 - DECEMBER 2026

            CS301 Data Structures and Algorithms   2 December 2026, 10:00
            CS302 Database Management Systems      4 December 2026, 14:00
            CS303 Computer Networks                7 December 2026, 10:00
            CS304 Operating Systems                9 December 2026, 14:00
            CS305 Software Engineering            11 December 2026, 10:00""",
            """EXAMINATION INSTRUCTIONS

            Candidates must report to the examination hall 30 minutes before
            the scheduled start time. Entry is not permitted more than
            15 minutes after the start.

            Programmable calculators are not allowed in CS303. A plain
            scientific calculator is permitted in CS304 only.

            Mobile phones and smart watches must be deposited outside the
            hall. Possession inside the hall is treated as unfair means.""",
        ],
    },
    {
        "filename": "syllabus_cse_sem5.pdf",
        "audience": {"audience_type": "class", "audience_branch": "CSE", "audience_semester": 5},
        "pages": [
            """CS301 DATA STRUCTURES AND ALGORITHMS - SYLLABUS

            Unit 1: Arrays, linked lists, stacks and queues.
            Unit 2: Trees, binary search trees, AVL trees and heaps.
            Unit 3: Graphs, traversal, shortest paths and spanning trees.
            Unit 4: Hashing, collision resolution and open addressing.
            Unit 5: Sorting, divide and conquer, dynamic programming.

            Credits: 4. Contact hours: 3 lectures and 1 tutorial per week.""",
            """CS302 DATABASE MANAGEMENT SYSTEMS - SYLLABUS

            Unit 1: The relational model, keys and relational algebra.
            Unit 2: SQL, nested queries, views and triggers.
            Unit 3: Normalisation up to the fourth normal form.
            Unit 4: Transactions, concurrency control and recovery.
            Unit 5: Indexing, B+ trees and query optimisation.

            Credits: 4. A laboratory component of 2 hours per week is
            assessed separately.""",
            """ASSESSMENT AND ATTENDANCE

            Each theory course is assessed out of 100 marks: 30 marks from
            internal assessment and 70 marks from the end semester
            examination. Internal assessment consists of two mid semester
            tests of 10 marks each and 10 marks for assignments.

            A minimum attendance of 75 percent is required to appear in the
            end semester examination. A student between 65 and 74 percent
            may apply to the dean for condonation on medical grounds, with
            supporting documents.""",
        ],
    },
    {
        "filename": "academic_calendar_2026.pdf",
        "audience": {"audience_type": "everyone"},
        "pages": [
            """ACADEMIC CALENDAR - ODD SEMESTER 2026-27

            Classes begin                     21 July 2026
            Last date for course registration 31 July 2026
            Mid semester examinations         15 to 19 September 2026
            Last date of fee payment          30 September 2026""",
            """ACADEMIC CALENDAR - CONTINUED

            Diwali break                      8 to 12 November 2026
            Last day of classes               28 November 2026
            End semester examinations         2 to 11 December 2026
            Semester ends                     18 December 2026
            Results declared                  5 January 2027""",
        ],
    },
    {
        "filename": "library_rules.pdf",
        "audience": {"audience_type": "everyone"},
        "pages": [
            """CENTRAL LIBRARY - RULES FOR BORROWERS

            An undergraduate student may borrow 4 books at a time for
            14 days. A postgraduate student may borrow 6 books for 21 days.

            An overdue book attracts a fine of 2 rupees per day. Reference
            books, journals and project reports are consulted in the reading
            room and are not issued.

            Library hours are 09:00 to 20:00 on working days and 10:00 to
            14:00 on Saturdays. The library is closed on Sundays and
            institute holidays.""",
        ],
    },
    {
        "filename": "scholarship_scheme.pdf",
        "audience": {"audience_type": "students"},
        "pages": [
            """MERIT SCHOLARSHIP SCHEME 2026-27

            A student with a cumulative grade point average of 9.0 or above
            in the previous two semesters is eligible for a merit
            scholarship covering 25 percent of tuition.

            A student with a CGPA between 8.5 and 8.99 is eligible for a
            scholarship covering 10 percent of tuition.

            Applications close on 31 August 2026.""",
            """MEANS BASED ASSISTANCE

            A student whose annual family income is below 400000 rupees may
            apply for means based assistance of up to 40000 rupees per year,
            subject to maintaining a CGPA of 7.0.

            Applications require an income certificate issued within the
            last six months and are considered by the scholarship committee
            in the first week of September.""",
        ],
    },
    {
        "filename": "faculty_circular.pdf",
        "audience": {"audience_type": "teachers"},
        "pages": [
            """CIRCULAR - FACULTY ONLY

            Annual appraisal forms must reach the office of the dean by
            15 October 2026. Forms received after that date will be
            considered in the next cycle.

            The revised pay scale takes effect from 1 November 2026 and will
            be reflected in the November salary.

            Heads of department are requested to submit the consolidated
            teaching load statement along with the appraisal forms.""",
        ],
    },
]


def write_pdfs(out_dir: str) -> list[str]:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    os.makedirs(out_dir, exist_ok=True)
    written = []
    for spec in DOCUMENTS:
        path = os.path.join(out_dir, spec["filename"])
        pdf = canvas.Canvas(path, pagesize=A4)
        width, height = A4
        for page_text in spec["pages"]:
            y = height - 30 * mm
            for raw_line in page_text.strip().split("\n"):
                line = raw_line.strip()
                pdf.setFont("Helvetica-Bold" if line.isupper() and line else "Helvetica", 11)
                pdf.drawString(25 * mm, y, line)
                y -= 7 * mm
            pdf.showPage()
        pdf.save()
        written.append(path)
        print(f"  wrote {path}  ({len(spec['pages'])} pages)")
    return written


def upload_all(out_dir: str, base_url: str, admin: str, password: str) -> None:
    import requests

    session = requests.Session()
    login = session.post(
        f"{base_url}/auth/login", json={"college_id": admin, "password": password}, timeout=30
    )
    if login.status_code != 200:
        sys.exit(f"[FATAL] Login failed ({login.status_code}): {login.text}")
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    for spec in DOCUMENTS:
        path = os.path.join(out_dir, spec["filename"])
        form = {k: str(v) for k, v in spec["audience"].items()}
        with open(path, "rb") as handle:
            response = session.post(
                f"{base_url}/ingest",
                headers=headers,
                files={"file": (spec["filename"], handle, "application/pdf")},
                data=form,
                timeout=120,
            )
        if response.status_code == 202:
            print(f"  queued {spec['filename']:34} audience={form.get('audience_type')}")
        else:
            print(f"  FAILED {spec['filename']:34} {response.status_code} {response.text[:120]}")

    print(
        "\nIndexing runs in the background. Poll GET /documents until every"
        "\nversion reports status 'ready' before asking questions."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/demo_pdfs", help="where to write the PDFs")
    parser.add_argument("--upload", action="store_true", help="also upload them as admin")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin", default="admin@bitmesra.ac.in")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args()

    print(f"Writing {len(DOCUMENTS)} synthetic documents to {args.out}/")
    write_pdfs(args.out)

    if args.upload:
        print(f"\nUploading to {args.base_url} as {args.admin}")
        upload_all(args.out, args.base_url, args.admin, args.password)
    else:
        print("\nAudience plan (pass --upload to apply it):")
        for spec in DOCUMENTS:
            audience = spec["audience"]
            label = audience["audience_type"]
            if label == "class":
                label = f"{audience['audience_branch']} sem {audience.get('audience_semester', 'all')}"
            print(f"  {spec['filename']:34} -> {label}")


if __name__ == "__main__":
    main()
