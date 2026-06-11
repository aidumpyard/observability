"""Heuristic scorer smoke test (pure functions, no servers)."""

from prism.evals.scorers import score_span


def _llm(**kw):
    base = dict(type="llm", span_id="s", trace_id="t", duration_ms=100,
                total_tokens=50, response_text="hello")
    base.update(kw)
    return base


def names(scores):
    return {s["name"]: s for s in scores}


def main():
    # non-llm spans are skipped
    assert score_span({"type": "chain", "span_id": "x"}) == []

    # nominal llm span
    s = names(score_span(_llm()))
    assert s["latency_slo"]["label"] == "ok"
    assert s["token_budget"]["label"] == "ok"
    assert s["answered"]["value"] == 1
    assert s["response_chars"]["value"] == 5
    assert "json_valid" not in s  # plain text, not json-ish

    # breaches + refusal
    s = names(score_span(_llm(duration_ms=12000, total_tokens=9000,
                              response_text="I'm sorry, I cannot help with that.")))
    assert s["latency_slo"]["label"] == "breach"
    assert s["token_budget"]["label"] == "breach"
    assert s["answered"]["label"] == "refusal" and s["answered"]["value"] == 0

    # empty response
    s = names(score_span(_llm(response_text="")))
    assert s["answered"]["label"] == "empty"

    # json validity
    s = names(score_span(_llm(response_text='{"value": 1}')))
    assert s["json_valid"]["value"] == 1
    s = names(score_span(_llm(response_text='{"value": oops}')))
    assert s["json_valid"]["value"] == 0 and s["json_valid"]["label"] == "invalid"

    print("✅ EVALS OK — heuristic scorers (latency/token/refusal/empty/json/length) all correct")


if __name__ == "__main__":
    main()
