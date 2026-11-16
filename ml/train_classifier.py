"""Predict whether a complaint will end with money paid back to the consumer.

Why this task: the CFPB no longer publishes complaint narratives. In November
2026, neither the API nor the bulk download file included them, so a model
can't learn from the complaint text. Instead it uses the facts known the moment
a complaint arrives.

Why a bank would care: if a complaints team knew which new complaints were
likely to cost money, they could look at those first.

Plain-language version:
- Target: 1 if the company's response was "Closed with monetary relief", else 0.
  Complaints still "In progress" are left out, since we don't know how they end.
- Features: product, sub-product, issue, sub-issue, company, state, channel, tags.
  Only things known at intake. We leave out anything decided later (whether the
  response was timely, the company's public statement), because using
  information from the future is called LEAKAGE and makes a model look better
  than it really is.
- One-hot encoding turns each category into yes/no columns ("is the product
  Credit card?"). Companies with fewer than 20 complaints share one "other"
  column, so the model doesn't memorize tiny companies.
- Logistic regression (from your stats courses), with class_weight="balanced"
  because payouts are rare and the model would otherwise just say "no" to everything.
- We hold back 20% of complaints the model never sees and score it on those.

Why not accuracy: if only 3% of complaints get a payout, a model that always says
"no payout" is 97% accurate and completely useless. So we report:
- ROC AUC: how well the model ranks payout cases above non-payout ones
  (0.5 = coin flip, 1.0 = perfect).
- Average precision vs. the base rate: random guessing scores about the payout rate.
- Top-10% capture: if a team reviewed only the 10% of complaints the model scores
  highest, what share of all payout cases would they catch? Random would be 10%.

Usage:
    python -m ml.train_classifier                     # from the warehouse (real data)
    python -m ml.train_classifier --sample tests/fixtures/sample_complaints.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

FEATURES = ["product", "sub_product", "issue", "sub_issue", "company", "state", "submitted_via", "tags"]
PAYOUT = "Closed with monetary relief"
MIN_ROWS = 1000          # fewer closed complaints than this isn't enough to learn from
MIN_PAYOUTS = 20

QUERY = """
    select product, sub_product, issue, sub_issue, company, state, submitted_via, tags, company_response
    from raw.complaints
    where company_response is not null and company_response <> 'In progress'
"""


def load_from_warehouse() -> pd.DataFrame:
    import psycopg2
    from pipeline.config import db_settings
    conn = psycopg2.connect(**db_settings())
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY)
            return pd.DataFrame(cur.fetchall(), columns=FEATURES + ["company_response"])
    finally:
        conn.close()


def load_from_sample(path: str) -> pd.DataFrame:
    df = pd.DataFrame([h["_source"] for h in json.load(open(path))])
    df["tags"] = df["tags"].apply(lambda t: ", ".join(t) if isinstance(t, list) else t)
    df = df[df["company_response"].notna() & (df["company_response"] != "In progress")]
    return df[FEATURES + ["company_response"]]


def top_share_captured(y_true: np.ndarray, scores: np.ndarray, share: float = 0.10) -> float:
    """Share of all payout cases found in the top `share` of complaints by model score."""
    n = max(1, int(len(scores) * share))
    top = np.argsort(-scores)[:n]
    return float(y_true[top].sum() / max(1, y_true.sum()))


def train(df: pd.DataFrame, seed: int = 42) -> dict:
    if len(df) < MIN_ROWS:
        raise ValueError(f"Only {len(df):,} closed complaints to learn from; need at least "
                         f"{MIN_ROWS:,}. Load more days first.")
    X = df[FEATURES].fillna("(missing)").astype(str)
    y = (df["company_response"] == PAYOUT).astype(int).to_numpy()
    if y.sum() < MIN_PAYOUTS:
        raise ValueError(f"Only {y.sum()} complaints ended in a payout; need at least {MIN_PAYOUTS}.")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=seed)
    model = Pipeline([
        ("onehot", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=20), FEATURES)])),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    model.fit(X_train, y_train)
    scores = model.predict_proba(X_test)[:, 1]
    pred = (scores >= 0.5).astype(int)

    # Which yes/no columns push a complaint most toward a payout?
    names = model.named_steps["onehot"].get_feature_names_out()
    coefs = model.named_steps["clf"].coef_[0]
    top = [(names[i].replace("cat__", ""), round(float(coefs[i]), 2)) for i in np.argsort(-coefs)[:10]]

    return {
        "model": model,
        "n_train": len(X_train), "n_test": len(X_test),
        "payout_rate": float(y_test.mean()),
        "roc_auc": float(roc_auc_score(y_test, scores)),
        "avg_precision": float(average_precision_score(y_test, scores)),
        "baseline_avg_precision": float(y_test.mean()),
        "top10_capture": top_share_captured(y_test, scores),
        "top10_capture_random": 0.10,
        "top_payout_signals": top,
        "report": classification_report(y_test, pred, target_names=["no payout", "payout"], zero_division=0),
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--sample")
    args = p.parse_args(argv)
    df = load_from_sample(args.sample) if args.sample else load_from_warehouse()
    r = train(df)
    print(f"Trained on {r['n_train']:,} closed complaints, tested on {r['n_test']:,} held out")
    print(f"Payout rate: {r['payout_rate']:.1%} of complaints end with money returned")
    print(f"ROC AUC: {r['roc_auc']:.3f}  (0.5 = coin flip, 1.0 = perfect)")
    print(f"Average precision: {r['avg_precision']:.3f}  (random guessing: {r['baseline_avg_precision']:.3f})")
    print(f"Top-10% capture: reviewing the 10% highest-scored complaints finds "
          f"{r['top10_capture']:.1%} of all payouts (random: 10%)")
    print("\nStrongest signals toward a payout:")
    for name, coef in r["top_payout_signals"]:
        print(f"  {coef:+.2f}  {name}")
    print("\n" + r["report"])

    import joblib
    out = Path("ml/artifacts"); out.mkdir(parents=True, exist_ok=True)
    joblib.dump(r["model"], out / "payout_classifier.joblib")
    json.dump({k: v for k, v in r.items() if k not in ("model", "report")},
              open(out / "metrics.json", "w"), indent=2)
    return r


if __name__ == "__main__":
    main()
