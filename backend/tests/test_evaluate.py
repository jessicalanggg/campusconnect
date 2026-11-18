from app.matching import evaluate as ev


def test_quick_evaluation_runs_and_reports():
    res = ev.run(ev.QUICK)
    text = ev.report(res)
    for heading in ("ILP vs greedy by class size", "Optimality", "Harder and easier populations", "Ablations",
                    "Scaling", "Limitations"):
        assert heading in text
    # Paired design: every algorithm in a trial saw the same population.
    trial = res["raw"]["main_30"][0]
    assert {"greedy", "local_search", "ilp"} <= trial.keys() and trial["n"] == 30
    # The ILP is seeded with the baselines, so it never loses on its own objective.
    assert all(r["paired"]["never_worse_on_objective"] for r in res["main"].values())
    assert set(res["ablations"]) == set(ev.ABLATIONS)


def test_confidence_interval_math():
    s = ev.summarize([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s["mean"] == 3.0 and round(s["sd"], 4) == 1.5811
    lo, hi = s["ci95"]
    assert round(lo, 2) == 1.03 and round(hi, 2) == 4.97  # 3 ± 2.78 * 1.581 / sqrt(5)
