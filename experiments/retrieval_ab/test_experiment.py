import numpy as np
import pytest

from experiments.retrieval_ab import experiment as E


def test_two_proportion_matches_a_hand_calculation():
    # 6,200 vs 6,650 conversions out of 100,000 each: pooled p = 0.06425, se = 0.0010966, z = 4.10
    r = E.two_proportion(6650, 100_000, 6200, 100_000)
    assert r["z"] == pytest.approx(4.10, abs=0.01)
    assert r["p_value"] < 1e-4
    assert r["ci95"] == pytest.approx([0.0024, 0.0066], abs=1e-4)
    assert r["relative_lift"] == pytest.approx(0.0726, abs=1e-4)


def test_sample_size_matches_the_textbook_value():
    # 50% -> 60%, alpha 0.05 two-sided, power 0.80: about 385-390 per arm depending on the approximation
    assert 380 <= E.required_n(0.5, mde=0.10) <= 395
    assert E.achieved_power(0.5, E.required_n(0.5, mde=0.10), mde=0.10) == pytest.approx(0.80, abs=0.01)


def test_assignment_is_balanced_and_random():
    arm = E.assign(101, np.random.default_rng(1))
    assert sorted(np.unique(arm, return_counts=True)[1]) == [50, 51]
    assert not (arm == E.assign(101, np.random.default_rng(2))).all()


def test_a_hit_requires_the_whole_sentence_in_one_chunk_of_the_right_document():
    filler = "Unrelated filler text about nothing in particular goes here. " * 40
    target = "Quantile regression estimates conditional medians rather than conditional means."
    docs = {"d1": filler + target + " " + filler, "d2": filler}
    ix = E.Index(docs, chunk_size=500, chunk_overlap=75)
    start = docs["d1"].index(target)
    q = "Quantile regression estimates conditional medians"
    assert ix.chars_to_hit(q, "d1", start, start + len(target)) <= E.BUDGET
    assert ix.chars_to_hit(q, "d2", start, start + len(target)) == np.inf       # right text, wrong document
    assert ix.chars_to_hit(q, "d1", 0, len(docs["d1"])) == np.inf               # span larger than any chunk


def test_aa_test_rejects_at_about_alpha():
    rng = np.random.default_rng(3)
    hits = rng.random(400) < 0.8
    assert 0.02 <= E.aa_false_positive_rate(hits, rng, n_sims=1000) <= 0.09
