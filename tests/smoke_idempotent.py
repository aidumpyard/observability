"""Score idempotency: re-submitting a score for (span_id,name,source) replaces,
not duplicates; different metric/source coexist."""

import os
import tempfile
import time

from prism.store import Writer, connect, init_db


def _count(db):
    c = connect(db, read_only=True)
    try:
        return c.execute("SELECT COUNT(*) n FROM scores").fetchone()["n"]
    finally:
        c.close()


def _val(db, span, name, source):
    c = connect(db, read_only=True)
    try:
        r = c.execute("SELECT value FROM scores WHERE span_id=? AND name=? AND source=?",
                      (span, name, source)).fetchone()
        return r["value"] if r else None
    finally:
        c.close()


def main():
    db = os.path.join(tempfile.mkdtemp(), "idem.db")
    init_db(db)
    w = Writer(db).start()

    sc = lambda v: {"span_id": "s1", "trace_id": "t1", "name": "judge_relevance",
                    "value": v, "label": "ok", "source": "llm_judge"}
    w.submit_scores([sc(4.0)]); time.sleep(0.5)
    w.submit_scores([sc(5.0)]); time.sleep(0.5)        # same key -> replace
    w.submit_scores([{"span_id": "s1", "trace_id": "t1", "name": "rouge_l",
                      "value": 0.7, "label": "PASS", "source": "reference"}])  # diff metric
    time.sleep(0.6); w.shutdown()

    n = _count(db)
    print("rows:", n, "(expect 2)")
    assert n == 2, n
    assert _val(db, "s1", "judge_relevance", "llm_judge") == 5.0, "latest value should win"
    assert _val(db, "s1", "rouge_l", "reference") == 0.7
    print("✅ IDEMPOTENT OK — re-scored span replaces, distinct metrics coexist")


if __name__ == "__main__":
    main()
