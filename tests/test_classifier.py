import pandas as pd
import pytest

from ml.train_classifier import FEATURES, load_from_sample, train


def test_model_beats_random_on_sample():
    r = train(load_from_sample("tests/fixtures/sample_complaints.json"))
    assert r["roc_auc"] > 0.6
    assert r["top10_capture"] > r["top10_capture_random"]


def test_clear_error_when_too_little_data():
    tiny = pd.DataFrame([{**{f: "x" for f in FEATURES}, "company_response": "Closed"}] * 10)
    with pytest.raises(ValueError, match="Load more days"):
        train(tiny)
