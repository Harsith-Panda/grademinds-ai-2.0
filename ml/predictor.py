from pathlib import Path

import joblib
import pandas as pd

MODEL_DIR = Path(__file__).parent / "models"
REG_PATH = MODEL_DIR / "linear_regression_model.pkl"
CLF_PATH = MODEL_DIR / "decision_tree_classifier.pkl"

FEATURE_NAMES = [
    "Study_Hours_per_Week",
    "Attendance_Rate",
    "Past_Exam_Scores",
    "Extracurricular_Activities_Yes",
]

# Dataset averages From Training Dataset (AVG)
FEATURE_AVERAGES = {
    "Study_Hours_per_Week": 26.53,
    "Attendance_Rate": 77.82,
    "Past_Exam_Scores": 77.72,
    "Extracurricular_Activities_Yes": 0.49,
}

FEATURE_LABELS = {
    "Study_Hours_per_Week": "Study hours per week",
    "Attendance_Rate": "Attendance rate (%)",
    "Past_Exam_Scores": "Past exam scores",
    "Extracurricular_Activities_Yes": "Extracurricular activities",
}

_reg_model = None
_clf_model = None
FEATURE_COEFFICIENTS = {}
FEATURE_IMPORTANCES = {}


def _load_models():
    global _reg_model, _clf_model, FEATURE_COEFFICIENTS, FEATURE_IMPORTANCES

    if _reg_model is None:
        if not REG_PATH.exists():
            raise FileNotFoundError(
                f"Regression model not found at {REG_PATH}. "
                "Copy linear_regression_model.pkl into ml/models/"
            )
        _reg_model = joblib.load(REG_PATH)

        coefs = _reg_model.coef_
        FEATURE_COEFFICIENTS = dict(zip(FEATURE_NAMES, coefs))

        print(f"[predictor] Loaded regression model from {REG_PATH}")
        print(f"[predictor] Coefficients: {FEATURE_COEFFICIENTS}")

    if _clf_model is None:
        if not CLF_PATH.exists():
            raise FileNotFoundError(
                f"Classifier not found at {CLF_PATH}. "
                "Copy decision_tree_classifier.pkl into ml/models/"
            )
        _clf_model = joblib.load(CLF_PATH)

        importances = _clf_model.feature_importances_
        FEATURE_IMPORTANCES = dict(zip(FEATURE_NAMES, importances))

        print(f"[predictor] Loaded classifier model from {CLF_PATH}")
        print(f"[predictor] Feature importances: {FEATURE_IMPORTANCES}")


# Core inference
def run_prediction(features: dict) -> dict:
    """
    Run both ML models on the student's input features.

    Args:
        features: dict with keys matching FEATURE_NAMES.
                  Extracurricular_Activities_Yes should be 0 or 1.

    Returns:
        {
            predicted_score:   float,
            pass_fail:         str,
            pass_probability:  float,
            fail_probability:  float,
            feature_gaps:      list[dict],
            input_features:    dict,
        }
    """
    _load_models()

    df = pd.DataFrame([{k: features[k] for k in FEATURE_NAMES}])

    # Regression
    predicted_score = float(_reg_model.predict(df)[0])
    predicted_score = round(max(0.0, min(100.0, predicted_score)), 2)

    # Classifier
    clf_label = int(_clf_model.predict(df)[0])
    clf_proba = _clf_model.predict_proba(df)[0]

    # proba index: [0]=FAIL, [1]=PASS
    pass_probability = (
        float(clf_proba[1]) if len(clf_proba) > 1 else float(clf_proba[0])
    )
    fail_probability = 1.0 - pass_probability
    pass_fail = "PASS" if clf_label == 1 else "FAIL"

    # Per-feature gap analysis
    feature_gaps = _compute_feature_gaps(features)

    print(
        f"[predictor] Score={predicted_score}, {pass_fail}, pass_prob={pass_probability:.2f}"
    )

    return {
        "predicted_score": predicted_score,
        "pass_fail": pass_fail,
        "pass_probability": pass_probability,
        "fail_probability": fail_probability,
        "feature_gaps": feature_gaps,
        "input_features": features,
    }


def _compute_feature_gaps(features: dict) -> list[dict]:
    """
    Compare each student feature against dataset average.
    Returns sorted list by impact (highest-impact gaps first).
    """
    gaps = []
    for feat in FEATURE_NAMES:
        student_val = features.get(feat, 0)
        avg_val = FEATURE_AVERAGES[feat]
        coef = FEATURE_COEFFICIENTS[feat]
        importance = FEATURE_IMPORTANCES[feat]
        label = FEATURE_LABELS[feat]

        if feat == "Extracurricular_Activities_Yes":
            gap_pct = None
            delta = student_val - avg_val
        else:
            delta = student_val - avg_val
            gap_pct = round((delta / avg_val) * 100, 1) if avg_val else 0

        score_impact = round(delta * coef, 2)

        gaps.append(
            {
                "feature": feat,
                "label": label,
                "student_value": round(student_val, 2),
                "average_value": round(avg_val, 2),
                "delta": round(delta, 2),
                "gap_pct": gap_pct,
                "score_impact": score_impact,
                "importance": importance,
                "is_below_avg": student_val < avg_val,
            }
        )

    gaps.sort(key=lambda x: x["score_impact"])
    return gaps


def get_feature_names() -> list[str]:
    return FEATURE_NAMES.copy()


def get_feature_labels() -> dict:
    return FEATURE_LABELS.copy()


def get_feature_averages() -> dict:
    return FEATURE_AVERAGES.copy()


def get_feature_coefficients() -> dict:
    """Get regression coefficients (requires model to be loaded)"""
    _load_models()
    return FEATURE_COEFFICIENTS.copy()


def get_feature_importances() -> dict:
    """Get classifier feature importances (requires model to be loaded)"""
    _load_models()
    return FEATURE_IMPORTANCES.copy()
