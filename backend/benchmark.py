"""Evaluate the published manuscript fixture against a real VeriCite API or its saved report."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import time

import httpx


FIXTURE = Path(__file__).with_name("fixtures") / "verification-benchmark.md"
MANUSCRIPT = FIXTURE.read_text(encoding="utf-8").split("```text\n", 1)[1].split("\n```", 1)[0]
PLANCK = "10.1051/0004-6361/201833910"
HUBBLE = "10.1073/pnas.15.3.168"
EXPECTED = [
    ("SUPPORTED", "[1]", PLANCK),
    ("CONTRADICTORY", "[1]", PLANCK),
    ("POSSIBLY_OUTDATED", "[2]", HUBBLE),
    ("UNVERIFIED", "[9]", None),
    ("UNVERIFIED", None, None),
]


def evaluate(report):
    rows = report.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Expected a backend verification report containing rows.")
    statements = MANUSCRIPT.split("\n\nReferences", 1)[0].splitlines()
    if len(statements) != len(EXPECTED):
        raise ValueError("Update the answer key to match the benchmark manuscript.")
    by_text = defaultdict(list)
    for row in rows:
        by_text[row["text"]].append(row)
    results = []
    for statement, (verdict, marker, doi) in zip(statements, EXPECTED):
        found = by_text[statement]
        errors = []
        if len(found) != 1:
            errors.append(f"Expected one row, received {len(found)}.")
        else:
            row = found[0]
            assessment = row.get("assessment") or {}
            actual = assessment.get("semantic_verdict") or "UNVERIFIED"
            if actual != verdict:
                errors.append(f"Expected {verdict}, received {actual}.")
            if row.get("marker") != marker or row.get("doi") != doi:
                errors.append("Citation marker or original DOI differs from the answer key.")
            if doi:
                passages = {p["passage_id"] for p in row.get("evidence", []) if p.get("verbatim_text", "").strip()}
                used = assessment.get("evidence_passage_ids") or []
                if (row.get("mapping") != "mapped" or assessment.get("assessment_status") != "assessed"
                        or not used or not set(used) <= passages or not assessment.get("explanation")):
                    errors.append("Missing assessment or evidence trace.")
            elif row.get("mapping") != "unmatched" or not row.get("review_reason") or row.get("reference"):
                errors.append("Missing or uncited reference was not preserved as a review item.")
            if verdict == "POSSIBLY_OUTDATED":
                update = assessment.get("update_evidence") or {}
                if not update.get("quote") or not update.get("url", "").startswith("https://"):
                    errors.append("Missing newer passage or publication link.")
        results.append({"statement": statement, "passed": not errors, "errors": errors})
    extra = sum(len(v) for k, v in by_text.items() if k not in statements)
    return {"passed": sum(item["passed"] for item in results), "expected": len(results),
            "unexpected_rows": extra, "cases": results}


def run_live(base):
    headers = {}
    if key := os.getenv("VERIFICATION_ACCESS_KEY"):
        headers["X-Verification-Key"] = key
    start = time.monotonic()
    with httpx.Client(base_url=base.rstrip("/"), timeout=30) as client:
        job = client.post("/api/verify", headers=headers, json={"text": MANUSCRIPT, "filename": "benchmark.txt"}).raise_for_status().json()
        auth = {"Authorization": "Bearer " + job["access_token"]}
        path = "/api/verify/" + job["job_id"]
        while time.monotonic() - start < 600:
            state = client.get(path, headers=auth).raise_for_status().json()
            if state["job_state"] == "completed":
                return client.get(path + "/report", headers=auth).raise_for_status().json()
            if state["job_state"] == "failed":
                raise ValueError(state.get("error_message") or "Verification job failed.")
            time.sleep(2)
    raise ValueError("Verification exceeded ten minutes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--api", help="Backend origin. Submits one public benchmark manuscript.")
    source.add_argument("--report", type=Path, help="Saved JSON from the backend report endpoint")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text()) if args.report else run_live(args.api)
        result = evaluate(report)
    except (httpx.HTTPError, OSError, KeyError, ValueError) as exc:
        print(f"Benchmark incomplete: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(result["passed"] != result["expected"] or result["unexpected_rows"] != 0)


if __name__ == "__main__":
    sys.exit(main())
