import os, time, random, warnings
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import pandas as pd
import joblib
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.svm import SVC
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, roc_curve, roc_auc_score

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data' / 'Placement_Data_Full_Class.csv'
MODEL = BASE / 'models' / 'placement_rf.joblib'
METRICS = BASE / 'models' / 'metrics.json'
URL = 'https://raw.githubusercontent.com/gouravkhator/Student-Placement-Prediction/refs/heads/master/Placement_Data_Full_Class.csv'
FEATURES = ['ssc_p', 'hsc_p', 'degree_p', 'workex', 'etest_p', 'mba_p', 'hsc_s', 'degree_t', 'specialisation']
NUMERIC = ['ssc_p', 'hsc_p', 'degree_p', 'etest_p', 'mba_p']
CATEGORICAL = ['workex', 'hsc_s', 'degree_t', 'specialisation']
REQUIRED_COLUMNS = set(FEATURES) | {'status'}
MIN_ROWS = 50
DOWNLOAD_RETRIES = 3


def _download(timeout=30):
    req = Request(URL, headers={'User-Agent': 'SmartPlacementPredictions/1.0'})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _validate_csv(raw_bytes):
    """Reject truncated/HTML-error-page downloads before they hit the training code."""
    import io
    df = pd.read_csv(io.BytesIO(raw_bytes))
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Downloaded dataset is missing expected columns: {sorted(missing)}')
    if len(df) < MIN_ROWS:
        raise ValueError(f'Downloaded dataset only has {len(df)} rows (expected at least {MIN_ROWS})')
    return df


def _generate_fallback_dataset(n=300, seed=42):
    """Used only when the real dataset cannot be downloaded and no cached copy
    exists locally (e.g. no internet access). This keeps the app usable end-to-end
    for a demo, but predictions trained on it are for illustration only -- swap in
    the real Kaggle/GitHub campus placement dataset for meaningful accuracy."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        ssc = round(rng.uniform(45, 98), 2)
        hsc = round(rng.uniform(40, 98), 2)
        degree = round(rng.uniform(45, 95), 2)
        etest = round(rng.uniform(40, 99), 2)
        mba = round(rng.uniform(50, 90), 2)
        workex = rng.choice(['Yes', 'No'])
        hsc_s = rng.choice(['Science', 'Commerce', 'Arts'])
        degree_t = rng.choice(['Sci&Tech', 'Comm&Mgmt', 'Others'])
        spec = rng.choice(['Mkt&Fin', 'Mkt&HR'])
        score = (ssc + hsc + degree + etest + mba) / 5 + (8 if workex == 'Yes' else 0)
        status = 'Placed' if score + rng.uniform(-10, 10) > 65 else 'Not Placed'
        rows.append({'ssc_p': ssc, 'hsc_p': hsc, 'degree_p': degree, 'workex': workex,
                     'etest_p': etest, 'mba_p': mba, 'hsc_s': hsc_s, 'degree_t': degree_t,
                     'specialisation': spec, 'status': status})
    return pd.DataFrame(rows)


def ensure_dataset():
    DATA.parent.mkdir(parents=True, exist_ok=True)
    if DATA.exists() and DATA.stat().st_size > 1000:
        return

    last_error = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            raw = _download()
            _validate_csv(raw)  # raises if malformed; we still write the raw bytes below
            DATA.write_bytes(raw)
            return
        except (OSError, ValueError, TimeoutError) as e:
            last_error = e
            if attempt < DOWNLOAD_RETRIES:
                time.sleep(1.5 * attempt)

    warnings.warn(
        f'Could not download the placement dataset after {DOWNLOAD_RETRIES} attempts '
        f'({last_error}). Falling back to a small synthetic dataset so the app keeps '
        f'working -- replace backend/data/Placement_Data_Full_Class.csv with the real '
        f'dataset for meaningful predictions.',
        stacklevel=2,
    )
    _generate_fallback_dataset().to_csv(DATA, index=False)


def train():
    ensure_dataset()
    df = pd.read_csv(DATA)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Dataset at {DATA} is missing columns: {sorted(missing)}')
    df = df[FEATURES + ['status']].copy()
    df['status'] = df['status'].map({'Placed': 1, 'Not Placed': 0})
    df = df.dropna(subset=['status'])
    if len(df) < 10:
        raise ValueError('Not enough labeled rows to train a model')
    X = df[FEATURES]
    y = df['status'].astype(int)
    pre = ColumnTransformer([
        ('num', SimpleImputer(strategy='median'), NUMERIC),
        ('cat', Pipeline([('imputer', SimpleImputer(strategy='most_frequent')), ('onehot', OneHotEncoder(handle_unknown='ignore'))]), CATEGORICAL)
    ])
    pipe = Pipeline([('preprocess', pre), ('model', RandomForestClassifier(n_estimators=400, max_depth=8, min_samples_leaf=2, class_weight='balanced', random_state=42))])
    stratify = y if y.nunique() > 1 else None
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=.2, stratify=stratify, random_state=42)
    pipe.fit(Xtr, ytr)
    yp = pipe.predict(Xte)
    metrics = {'accuracy': round(float(accuracy_score(yte, yp)), 4),
               'precision': round(float(precision_score(yte, yp, zero_division=0)), 4),
               'recall': round(float(recall_score(yte, yp, zero_division=0)), 4),
               'f1': round(float(f1_score(yte, yp, zero_division=0)), 4),
               'dataset_rows': int(len(df))}
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, MODEL)
    METRICS.write_text(__import__('json').dumps(metrics, indent=2))
    return metrics


def load_model():
    if not MODEL.exists():
        train()
    return joblib.load(MODEL)


# ---------------------------------------------------------------------------
# Four-algorithm comparison used by the project demo/reporting screen.
# Each manual evaluation uses the same train/test split so the four accuracy
# values are directly comparable for the selected dataset.
# ---------------------------------------------------------------------------
ALGORITHM_LABELS = {
    'random_forest': 'Random Forest',
    'logistic_regression': 'Logistic Regression',
    'decision_tree': 'Decision Tree',
    'svm': 'Support Vector Machine (SVM)',
}


def _load_training_frame():
    ensure_dataset()
    df = pd.read_csv(DATA)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f'Dataset at {DATA} is missing columns: {sorted(missing)}')
    df = df[FEATURES + ['status']].copy()
    df['status'] = df['status'].map({'Placed': 1, 'Not Placed': 0})
    return df.dropna(subset=['status'])


def _preprocessor():
    return ColumnTransformer([
        ('num', SimpleImputer(strategy='median'), NUMERIC),
        ('cat', Pipeline([
            ('imputer', SimpleImputer(strategy='most_frequent')),
            ('onehot', OneHotEncoder(handle_unknown='ignore'))
        ]), CATEGORICAL)
    ])


def _algorithm_estimator(name):
    key = str(name or 'random_forest').strip().lower()
    if key == 'logistic_regression':
        return LogisticRegression(max_iter=2000, class_weight='balanced', random_state=42)
    if key == 'decision_tree':
        return DecisionTreeClassifier(max_depth=8, min_samples_leaf=2, class_weight='balanced', random_state=42)
    if key == 'svm':
        return SVC(C=1.0, kernel='rbf', probability=True, class_weight='balanced', random_state=42)
    return RandomForestClassifier(n_estimators=400, max_depth=8, min_samples_leaf=2, class_weight='balanced', random_state=42)


def _algorithm_pipeline(name):
    return Pipeline([('preprocess', _preprocessor()), ('model', _algorithm_estimator(name))])


def evaluate_algorithms():
    """Evaluate four classifiers on one reproducible stratified holdout."""
    df = _load_training_frame()
    X, y = df[FEATURES], df['status'].astype(int)
    stratify = y if y.nunique() > 1 else None
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=.2, stratify=stratify, random_state=42)
    results = []
    for key, label in ALGORITHM_LABELS.items():
        pipe = _algorithm_pipeline(key)
        pipe.fit(Xtr, ytr)
        yp = pipe.predict(Xte)
        matrix = confusion_matrix(yte, yp, labels=[0, 1]).tolist()
        roc_points = []
        auc = None
        if yte.nunique() == 2 and hasattr(pipe, 'predict_proba'):
            try:
                scores = pipe.predict_proba(Xte)[:, 1]
                fpr, tpr, _ = roc_curve(yte, scores)
                auc = round(float(roc_auc_score(yte, scores)), 4)
                # Keep the response compact while preserving the curve shape.
                stride = max(1, len(fpr) // 45)
                roc_points = [[round(float(fpr[i]), 4), round(float(tpr[i]), 4)] for i in range(0, len(fpr), stride)]
                if roc_points[-1] != [1.0, 1.0]:
                    roc_points.append([1.0, 1.0])
            except (ValueError, IndexError):
                roc_points = []
        results.append({
            'algorithm_key': key,
            'algorithm': label,
            'accuracy': round(float(accuracy_score(yte, yp)) * 100, 2),
            'precision': round(float(precision_score(yte, yp, zero_division=0)) * 100, 2),
            'recall': round(float(recall_score(yte, yp, zero_division=0)) * 100, 2),
            'f1': round(float(f1_score(yte, yp, zero_division=0)) * 100, 2),
            'confusion_matrix': matrix,
            'roc_auc': auc,
            'roc_curve': roc_points,
            'dataset_rows': int(len(df)),
            'test_rows': int(len(yte)),
        })
    return results


def predict_with_algorithm(name, row):
    """Train the selected classifier on the full current dataset and predict one student."""
    df = _load_training_frame()
    X, y = df[FEATURES], df['status'].astype(int)
    pipe = _algorithm_pipeline(name)
    pipe.fit(X, y)
    one = pd.DataFrame([row])
    probability = float(pipe.predict_proba(one)[0][1] * 100)
    return round(probability, 1), ALGORITHM_LABELS.get(str(name).lower(), ALGORITHM_LABELS['random_forest'])
