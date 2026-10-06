"""Randomized offline experiment: does a smaller chunk size retrieve better?

    python -m experiments.retrieval_ab.experiment

Control (A)    the chunking the app ships with: 1,000 characters, 150 overlap
Treatment (B)  500 characters, 75 overlap

Unit of randomization: one query. Each query is assigned to exactly one arm,
as a user would be in an online A/B test. Both arms get the same amount of
retrieved text (5,000 characters), so B is not penalised or favoured for
having smaller chunks.

Everything that could be tuned after seeing results (seed, metrics, alpha,
power, minimum detectable effect) is fixed in the constants below.
"""
import json
import re
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from scipy import stats
from statsmodels.stats.contingency_tables import mcnemar
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize, proportions_ztest

from backend.embeddings_provider import LocalHashEmbeddings

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results.json"

CORPUS = {
    "china_cbdc": "uploads/China17.pdf",
    "long_run_risks": "uploads/w13196.pdf",
    "ocr_manuscripts": "uploads/102305450111012041758/computer_vision.pdf",
}
ARMS = {"A": {"chunk_size": 1000, "chunk_overlap": 150}, "B": {"chunk_size": 500, "chunk_overlap": 75}}
BUDGET = 5000            # characters of retrieved context, primary metric
SMALL_BUDGETS = (2000, 1000)   # secondary metrics: the same question with less context
SEED = 20261006          # fixed before any outcome was computed
ALPHA = 0.05
POWER = 0.80
MDE = 0.10               # smallest absolute change in hit rate worth acting on
PILOT_N = 60             # queries used only to estimate the baseline rate
KEEP_SHARE = 0.6         # share of a sentence's content words kept in the query
N_BOOT = 10_000
N_AA = 2_000

STOP = set("""a an the and or but if then than that this these those of in on at by for with from to into over under about
as is are was were be been being it its their there which who whom whose what when where why how not no nor so such can could
may might must shall should will would do does did done have has had having we our us they them he she his her you your i
also more most less many much some any each other between within across per via while during after before both either""".split())


# ---------------------------------------------------------------- corpus and queries
def load_corpus():
    docs = {}
    for name, rel in CORPUS.items():
        text = " ".join((p.extract_text() or "") for p in PdfReader(str(ROOT / rel)).pages)
        docs[name] = re.sub(r"\s+", " ", text).strip()
    return docs


def content_words(sentence):
    return [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", sentence) if w.lower() not in STOP]


def build_queries(docs, rng):
    """One query per eligible sentence: a random 60% of its content words, in order.

    The sentence's character span is the ground truth: a retrieval counts as a
    hit when one retrieved chunk contains the whole sentence.
    """
    rows = []
    for doc, text in docs.items():
        for m in re.finditer(r"[A-Z][^.!?]{50,500}[.!?](?= )", text):
            s = m.group(0)
            words = content_words(s)
            alpha = sum(c.isalpha() or c == " " for c in s) / len(s)
            if len(words) < 6 or alpha < 0.80:
                continue                                   # skip tables, equations, reference lists
            keep = sorted(rng.choice(len(words), size=max(4, round(KEEP_SHARE * len(words))), replace=False))
            rows.append({"doc": doc, "start": m.start(), "end": m.end(), "n_words": len(s.split()),
                         "query": " ".join(words[i] for i in keep)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- retrieval
class Index:
    """One arm: chunk every document, embed with the app's offline embedder, search with FAISS."""

    def __init__(self, docs, chunk_size, chunk_overlap):
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                                                  add_start_index=True)
        self.meta = []
        texts = []
        for doc, text in docs.items():
            for d in splitter.create_documents([text]):
                self.meta.append((doc, d.metadata["start_index"], d.metadata["start_index"] + len(d.page_content)))
                texts.append(d.page_content)
        self.emb = LocalHashEmbeddings()
        vecs = np.asarray(self.emb.embed_documents(texts), dtype="float32")
        self.index = faiss.IndexFlatIP(vecs.shape[1])
        self.index.add(vecs)
        self.k = BUDGET // chunk_size
        self.chunk_size = chunk_size

    def chars_to_hit(self, query, doc, start, end):
        """Characters of context read before a chunk containing the target appears (inf if never)."""
        q = np.asarray([self.emb.embed_query(query)], dtype="float32")
        _, idx = self.index.search(q, self.k)
        for rank, i in enumerate(idx[0], start=1):
            d, s, e = self.meta[i]
            if d == doc and s <= start and e >= end:
                return rank * self.chunk_size
        return np.inf


def score(queries, indexes):
    out = queries.copy()
    for arm, ix in indexes.items():
        out[f"cth_{arm}"] = [ix.chars_to_hit(r.query, r.doc, r.start, r.end) for r in queries.itertuples()]
    return out


# ---------------------------------------------------------------- statistics
def required_n(p0, mde=MDE, alpha=ALPHA, power=POWER):
    es = proportion_effectsize(min(p0 + mde, 0.999), p0)
    return int(np.ceil(NormalIndPower().solve_power(effect_size=es, alpha=alpha, power=power, alternative="two-sided")))


def achieved_power(p0, n, mde=MDE, alpha=ALPHA):
    es = proportion_effectsize(min(p0 + mde, 0.999), p0)
    return float(NormalIndPower().power(effect_size=es, nobs1=n, alpha=alpha, alternative="two-sided"))


def two_proportion(x_b, n_b, x_a, n_a, rng=None):
    """Treatment minus control, with z-test, Wald interval and (optionally) a bootstrap interval."""
    p_a, p_b = x_a / n_a, x_b / n_b
    z, p = proportions_ztest([x_b, x_a], [n_b, n_a])
    se = np.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    res = {"control_rate": float(p_a), "treatment_rate": float(p_b), "diff": float(p_b - p_a),
           "relative_lift": float(p_b / p_a - 1) if p_a else None, "z": float(z), "p_value": float(p),
           "ci95": [float(p_b - p_a - 1.96 * se), float(p_b - p_a + 1.96 * se)],
           "cohens_h": float(proportion_effectsize(p_b, p_a))}
    if rng is not None:
        boot = rng.binomial(n_b, p_b, N_BOOT) / n_b - rng.binomial(n_a, p_a, N_BOOT) / n_a
        res["bootstrap_ci95"] = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    return res


def analyse(d, rng):
    """d: one row per query with columns arm, hit, cth (chars of context read before the hit), doc, n_words."""
    a, b = d[d.arm == "A"], d[d.arm == "B"]
    primary = two_proportion(b.hit.sum(), len(b), a.hit.sum(), len(a), rng)

    secondary = {f"hit_rate_{bud}_chars": two_proportion((b.cth <= bud).sum(), len(b), (a.cth <= bud).sum(), len(a))
                 for bud in SMALL_BUDGETS}
    adj = multipletests([v["p_value"] for v in secondary.values()], alpha=ALPHA, method="holm")[1]
    for v, p_adj in zip(secondary.values(), adj):
        v["p_holm"] = float(p_adj)

    by_doc = {}
    for doc, g in d.groupby("doc"):
        ga, gb = g[g.arm == "A"], g[g.arm == "B"]
        by_doc[doc] = {"n_control": int(len(ga)), "n_treatment": int(len(gb)),
                       **two_proportion(gb.hit.sum(), len(gb), ga.hit.sum(), len(ga))}
    y = d.assign(hit=d.hit.astype(int), treat=(d.arm == "B").astype(int))
    full = smf.logit("hit ~ treat * C(doc)", y).fit(disp=0)
    main = smf.logit("hit ~ treat + C(doc)", y).fit(disp=0)
    lr = 2 * (full.llf - main.llf)
    interaction = {"lr_stat": float(lr), "df": int(full.df_model - main.df_model),
                   "p_value": float(stats.chi2.sf(lr, full.df_model - main.df_model))}

    balance = {"n_control": int(len(a)), "n_treatment": int(len(b)),
               "srm_p_value": float(stats.chisquare([len(a), len(b)]).pvalue),
               "sentence_length_p_value": float(stats.ttest_ind(a.n_words, b.n_words, equal_var=False).pvalue),
               "document_mix_p_value": float(stats.chi2_contingency(pd.crosstab(d.arm, d.doc))[1])}
    return {"primary_hit_rate_5000_chars": primary, "secondary": secondary,
            "by_document": by_doc, "document_interaction": interaction, "balance_checks": balance}


def assign(n, rng):
    """Complete randomization: exactly half of the queries to each arm."""
    arm = np.array(["A"] * (n // 2) + ["B"] * (n - n // 2))
    rng.shuffle(arm)
    return arm


def aa_false_positive_rate(hits_a, rng, n_sims=N_AA):
    """Both groups get the control. A sound test should reject about alpha of the time."""
    n = len(hits_a)
    rejections = 0
    for _ in range(n_sims):
        arm = assign(n, rng)
        x1, x2 = hits_a[arm == "A"], hits_a[arm == "B"]
        _, p = proportions_ztest([x2.sum(), x1.sum()], [len(x2), len(x1)])
        rejections += p < ALPHA
    return rejections / n_sims


def paired_reference(scored):
    """Every query scored under both arms. Not the experiment: shown for comparison with a paired design."""
    ha, hb = scored.cth_A <= BUDGET, scored.cth_B <= BUDGET
    table = pd.crosstab(ha, hb).reindex(index=[False, True], columns=[False, True], fill_value=0)
    m = mcnemar(table, exact=False, correction=True)
    return {"n": int(len(scored)), "control_rate": float(ha.mean()), "treatment_rate": float(hb.mean()),
            "diff": float(hb.mean() - ha.mean()), "only_control_hits": int(table.loc[True, False]),
            "only_treatment_hits": int(table.loc[False, True]), "mcnemar_p_value": float(m.pvalue)}


# ---------------------------------------------------------------- run
def main():
    rng = np.random.default_rng(SEED)
    docs = load_corpus()
    queries = build_queries(docs, rng).sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    indexes = {arm: Index(docs, **cfg) for arm, cfg in ARMS.items()}

    # 1. Pilot: estimate the control hit rate on queries that take no part in the experiment.
    pilot, pool = queries.iloc[:PILOT_N], queries.iloc[PILOT_N:].reset_index(drop=True)
    p0 = float((score(pilot, {"A": indexes["A"]}).cth_A <= BUDGET).mean())

    # 2. Design: sample size for the chosen minimum detectable effect.
    n_needed = required_n(p0)
    n_arm = len(pool) // 2            # rule set in advance: use every available query, required_n is the minimum
    detectable = next((m for m in np.arange(0.01, 0.5, 0.005) if achieved_power(p0, n_arm, mde=m) >= POWER), None)
    design = {"alpha": ALPHA, "target_power": POWER, "mde_abs": MDE, "pilot_n": PILOT_N, "pilot_control_rate": p0,
              "required_per_arm": n_needed, "available_queries": int(len(pool)), "used_per_arm": int(n_arm),
              "achieved_power_at_mde": achieved_power(p0, n_arm),
              "adequately_powered": bool(n_arm >= n_needed),
              "smallest_effect_detectable_at_target_power": None if detectable is None else float(round(detectable, 3))}

    # 3. Randomize and observe each query under its own arm only.
    exp = pool.iloc[:2 * n_arm].copy()
    exp["arm"] = assign(len(exp), rng)
    both = score(exp, indexes)
    exp["cth"] = np.where(exp.arm == "A", both.cth_A, both.cth_B)
    exp["hit"] = exp.cth <= BUDGET

    # 4. Analyse.
    result = analyse(exp, rng)
    primary = result["primary_hit_rate_5000_chars"]
    lo, hi = primary["ci95"]
    if primary["p_value"] < ALPHA and primary["diff"] > 0:
        decision = "Adopt 500-character chunks: retrieval hit rate is higher and the difference is statistically significant."
    elif primary["p_value"] < ALPHA:
        decision = "Keep 1,000-character chunks: the smaller chunks retrieve significantly worse."
    elif max(abs(lo), abs(hi)) < MDE:
        decision = "Keep 1,000-character chunks: no significant difference, and the interval rules out a change as large as the minimum effect of interest."
    else:
        decision = "Keep 1,000-character chunks for now: no significant difference, but the interval is too wide to rule out a meaningful one."

    summary = {
        "arms": ARMS, "context_budget_chars": BUDGET, "seed": SEED,
        "corpus": {name: {"chars": len(t)} for name, t in docs.items()},
        "chunks": {arm: len(ix.meta) for arm, ix in indexes.items()},
        "eligible_queries": int(len(queries)), "design": design, **result,
        "aa_test_false_positive_rate": float(aa_false_positive_rate((both.cth_A <= BUDGET).to_numpy(), rng)),
        "paired_reference_not_the_experiment": paired_reference(both), "decision": decision,
    }
    OUT.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
