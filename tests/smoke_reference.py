"""Reference scorer smoke: rouge_l verdicts, input-hash matching, sha256."""

from prism.evals.reference import load_references, rouge_l, score_span, sha256


def main():
    # paraphrase -> decent overlap
    r = rouge_l("The account was suspended due to missed payments.",
                "Account suspended after missed payments.")
    assert 0 < r["value"] <= 1 and r["verdict"] in ("PASS", "WARN"), r

    # unrelated -> FAIL
    bad = rouge_l("The transaction was flagged for manual review.",
                  "The weather forecast shows rain tomorrow.")
    assert bad["verdict"] == "FAIL", bad

    # exact match -> 1.0 PASS
    assert rouge_l("hello world foo", "hello world foo")["value"] == 1.0

    # score_span matches by input hash
    span = {"type": "llm", "span_id": "s", "trace_id": "t",
            "user_message": "summarise the report", "response_text": "the report summary"}
    refs = {sha256("summarise the report"): "the report summary"}
    sc = score_span(span, refs)
    assert sc and sc[0]["name"] == "rouge_l" and sc[0]["source"] == "reference"
    assert sc[0]["value"] == 1.0 and sc[0]["label"] == "PASS"

    # no reference for this input -> no score
    assert score_span(span, {}) == []
    # non-llm -> no score
    assert score_span({"type": "chain"}, refs) == []

    print("✅ REFERENCE OK — rouge_l verdicts, input-hash matching, sha256")


if __name__ == "__main__":
    main()
