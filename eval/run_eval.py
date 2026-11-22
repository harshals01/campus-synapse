"""
Evaluation harness.

Reports separate measurements rather than one "accuracy" number, because they
answer different questions and fail for different reasons:

  retrieval hit rate@k   did the right evidence come back at all?
  citation page accuracy did the answer point at the page the fact is on?
  correct abstention     did it stay silent when the documents cannot answer?
  false abstention       did it stay silent when they could?

Two modes, because they need different things:

  retrieval  Imports the search layer directly and compares dense-only,
             keyword-only and hybrid retrieval. Needs the real embedding model
             and the database, but no running server and no Groq key.

  answers    Calls POST /chat over HTTP for end-to-end behaviour: citations,
             abstention and latency. Needs a running server and a Groq key.

Usage:
    python -m eval.run_eval retrieval --questions eval/questions.jsonl
    python -m eval.run_eval answers   --questions eval/questions.jsonl \
        --split dev --password student123

Report the development split while tuning. Run the test split **once**, at the
end, and record the commit hash alongside the numbers.
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import defaultdict

CONFIGS = ("dense", "keyword", "hybrid")


# ── Question set ──────────────────────────────────────────────────────────────

def load_questions(path: str, split: str | None) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                sys.exit(f"[FATAL] {path}:{line_number} is not valid JSON: {exc}")
            for field in ("id", "split", "asker", "question", "answerable"):
                if field not in row:
                    sys.exit(f"[FATAL] {path}:{line_number} is missing '{field}'")
            if row["answerable"] and not row.get("gold_document"):
                sys.exit(f"[FATAL] {path}:{line_number} is answerable but has no gold_document")
            rows.append(row)
    if split:
        rows = [r for r in rows if r["split"] == split]
    if not rows:
        sys.exit(f"[FATAL] no questions loaded from {path}" + (f" for split={split}" if split else ""))
    return rows


def summarise(rows: list[dict]) -> str:
    answerable = sum(1 for r in rows if r["answerable"])
    return (
        f"{len(rows)} questions: {answerable} answerable, "
        f"{len(rows) - answerable} unsupported"
    )


# ── Retrieval mode ────────────────────────────────────────────────────────────

class _QuietLogger:
    def info(self, *_a, **_k): pass
    warning = error = info


def run_retrieval(questions: list[dict], ks: tuple[int, ...], out_prefix: str) -> None:
    """Compare retrieval configurations on the answerable questions."""
    from backend.config import INDEX_NAME
    from backend.database import SessionLocal
    from backend.models.db_models import Document, User
    from backend.services.access_policy import allowed_document_versions
    from backend.services.embedding_service import get_embedding
    from backend.services.fusion_service import rrf_fusion
    from backend.services.qdrant_service import (
        doc_version_filter,
        keyword_search,
        semantic_search,
    )

    logger = _QuietLogger()
    db = SessionLocal()
    rows_out = []

    try:
        answerable = [q for q in questions if q["answerable"]]
        print(f"Retrieval over {len(answerable)} answerable questions, k={list(ks)}\n")

        for question in answerable:
            user = db.query(User).filter(User.college_id == question["asker"]).first()
            if user is None:
                sys.exit(f"[FATAL] no such account: {question['asker']}")
            scope = allowed_document_versions(user, db)

            gold = (
                db.query(Document)
                .filter(Document.display_name == question["gold_document"])
                .filter(Document.deleted_at.is_(None))
                .first()
            )
            if gold is None:
                sys.exit(
                    f"[FATAL] {question['id']}: no document named "
                    f"{question['gold_document']!r} is loaded"
                )
            gold_pages = set(question.get("gold_pages") or [])

            if not scope:
                for config in CONFIGS:
                    rows_out.append({"id": question["id"], "config": config, **{f"hit@{k}": 0 for k in ks}})
                continue

            access_filter = doc_version_filter(scope)
            top_k = max(ks)
            dense = semantic_search(
                INDEX_NAME, get_embedding(question["question"]), top_k, access_filter
            )["hits"]["hits"]
            lexical = keyword_search(INDEX_NAME, question["question"], access_filter)["hits"]["hits"]
            fused = [
                {"_source": row["source"]} for row in rrf_fusion(dense, lexical)
            ]

            ranked = {"dense": dense, "keyword": lexical, "hybrid": fused}
            for config, hits in ranked.items():
                record = {"id": question["id"], "config": config, "question": question["question"]}
                for k in ks:
                    found = False
                    for hit in hits[:k]:
                        source = hit["_source"]
                        if source.get("document_id") != gold.id:
                            continue
                        if not gold_pages or source.get("page_number") in gold_pages:
                            found = True
                            break
                    record[f"hit@{k}"] = int(found)
                rows_out.append(record)
    finally:
        db.close()

    # ── Report ────────────────────────────────────────────────────────────────
    totals = defaultdict(lambda: defaultdict(int))
    for row in rows_out:
        for k in ks:
            totals[row["config"]][k] += row[f"hit@{k}"]
    n = len({row["id"] for row in rows_out})

    header = "| Configuration | " + " | ".join(f"Hit rate@{k}" for k in ks) + " |"
    divider = "|---|" + "---|" * len(ks)
    lines = ["## Retrieval hit rate", "", f"Answerable questions: {n}", "", header, divider]
    for config in CONFIGS:
        cells = [f"{totals[config][k]}/{n} ({100 * totals[config][k] / n:.0f}%)" for k in ks]
        lines.append(f"| {config} | " + " | ".join(cells) + " |")
    report = "\n".join(lines)
    print(report)

    _write_csv(f"{out_prefix}_retrieval.csv", rows_out)
    _write_text(f"{out_prefix}_retrieval.md", report)


# ── Answers mode ──────────────────────────────────────────────────────────────

def run_answers(questions: list[dict], base_url: str, password: str, out_prefix: str) -> None:
    """End-to-end behaviour through the API: citations, abstention, latency."""
    import requests

    session = requests.Session()
    tokens: dict[str, str] = {}

    def token_for(college_id: str) -> str:
        if college_id not in tokens:
            response = session.post(
                f"{base_url}/auth/login",
                json={"college_id": college_id, "password": password},
                timeout=30,
            )
            if response.status_code != 200:
                sys.exit(
                    f"[FATAL] login failed for {college_id}: "
                    f"{response.status_code} {response.text[:200]}"
                )
            tokens[college_id] = response.json()["access_token"]
        return tokens[college_id]

    rows_out = []
    print(f"Asking {len(questions)} questions at {base_url}\n")

    for question in questions:
        headers = {"Authorization": f"Bearer {token_for(question['asker'])}"}
        started = time.perf_counter()
        response = session.post(
            f"{base_url}/chat",
            headers=headers,
            json={"messages": [{"role": "user", "content": question["question"]}]},
            timeout=180,
        )
        elapsed = time.perf_counter() - started

        if response.status_code != 200:
            print(f"  {question['id']}: HTTP {response.status_code} {response.text[:120]}")
            rows_out.append({
                "id": question["id"], "answerable": question["answerable"],
                "error": f"HTTP {response.status_code}", "latency_s": round(elapsed, 2),
            })
            continue

        body = response.json()
        cited_pages = [c.get("page_number") for c in body.get("citations", [])]
        gold_pages = set(question.get("gold_pages") or [])
        page_ok = bool(gold_pages) and any(p in gold_pages for p in cited_pages)

        rows_out.append({
            "id": question["id"],
            "split": question["split"],
            "answerable": question["answerable"],
            "question": question["question"],
            "abstained": body.get("abstained"),
            "top_similarity": round(body.get("top_similarity") or 0, 4),
            "top_fusion_score": round(body.get("top_fusion_score") or 0, 4),
            "hits_used": body.get("hits_used"),
            "cited_documents": ";".join(sorted({c["display_name"] for c in body.get("citations", [])})),
            "cited_pages": ";".join(str(p) for p in cited_pages),
            "gold_document": question.get("gold_document", ""),
            "gold_pages": ";".join(str(p) for p in sorted(gold_pages)),
            "page_correct": int(page_ok),
            "latency_s": round(elapsed, 2),
            "reply": (body.get("reply") or "").replace("\n", " ")[:400],
        })
        flag = "abstained" if body.get("abstained") else ("page ok" if page_ok else "page MISS")
        print(f"  {question['id']:6} {flag:10} sim={rows_out[-1]['top_similarity']:.3f}  {question['question'][:58]}")

    answerable = [r for r in rows_out if r.get("answerable") and "error" not in r]
    unsupported = [r for r in rows_out if not r.get("answerable") and "error" not in r]
    answered = [r for r in answerable if not r["abstained"]]
    latencies = [r["latency_s"] for r in rows_out if "latency_s" in r]

    def rate(count, total):
        return f"{count}/{total} ({100 * count / total:.0f}%)" if total else "n/a (0)"

    lines = [
        "## End-to-end results",
        "",
        f"- Answerable: {len(answerable)}   Unsupported: {len(unsupported)}",
        "",
        "| Metric | Value | Measured on |",
        "|---|---|---|",
        f"| Citation page accuracy | {rate(sum(r['page_correct'] for r in answered), len(answered))} | answered |",
        f"| False abstention | {rate(sum(1 for r in answerable if r['abstained']), len(answerable))} | answerable |",
        f"| Correct abstention | {rate(sum(1 for r in unsupported if r['abstained']), len(unsupported))} | unsupported |",
        f"| Median latency | {statistics.median(latencies):.2f} s | all |" if latencies else "",
        f"| 90th percentile latency | {sorted(latencies)[int(0.9 * (len(latencies) - 1))]:.2f} s | all |" if latencies else "",
        "",
        "Answer correctness is **not** scored here: mark each answered row against",
        "`gold_answer_points` by hand in the CSV and report that separately.",
        "",
        "With a question set this small, quote the counts as well as the percentages.",
    ]
    report = "\n".join(line for line in lines if line != "")
    print("\n" + report)

    _write_csv(f"{out_prefix}_answers.csv", rows_out)
    _write_text(f"{out_prefix}_answers.md", report)


# ── Output ────────────────────────────────────────────────────────────────────

def _write_csv(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {path}")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    print(f"wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["retrieval", "answers"])
    parser.add_argument("--questions", default="eval/questions.jsonl")
    parser.add_argument("--split", choices=["dev", "test"], default=None,
                        help="omit to run everything; use 'test' only for the final report")
    parser.add_argument("--k", default="3,5", help="cut-offs for retrieval hit rate")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default="student123",
                        help="shared password for the evaluation accounts")
    parser.add_argument("--out", default="eval/results", help="output path prefix")
    args = parser.parse_args()

    questions = load_questions(args.questions, args.split)
    print(f"{summarise(questions)}" + (f" (split={args.split})" if args.split else "") + "\n")

    if args.split == "test":
        print("NOTE: this is the held-out split. Run it once and record the commit hash.\n")

    if args.mode == "retrieval":
        ks = tuple(int(x) for x in args.k.split(","))
        run_retrieval(questions, ks, args.out)
    else:
        run_answers(questions, args.base_url, args.password, args.out)


if __name__ == "__main__":
    main()
