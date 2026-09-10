"""
ai-engine/src/ml/applicability_model.py

Singleton loader and inference wrapper for the V1 BIS applicability model.

Usage
-----
    from src.ml.applicability_model import load_applicability_model, get_applicability_model

    # Call once at startup (e.g., in Recommender.__init__):
    load_applicability_model(model_path, metadata_path)

    # Anywhere else:
    model = get_applicability_model()
    result = model.predict(features_df)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import joblib
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_instance: Optional["ApplicabilityModel"] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_applicability_model(
    model_path: str,
    metadata_path: str,
) -> Optional["ApplicabilityModel"]:
    """
    Load (or reload) the singleton ApplicabilityModel from disk.

    Returns the loaded model on success, or None on failure.
    Errors are logged but never raised -- callers must handle None.
    """
    global _instance
    try:
        _instance = ApplicabilityModel(model_path, metadata_path)

        # Prevent thread explosion on small containers by forcing single-threaded execution for inference
        try:
            classifier = _instance.pipeline.named_steps.get("model")
            if classifier and hasattr(classifier, "n_jobs"):
                classifier.n_jobs = 1
                logger.info("Set RandomForestClassifier n_jobs=1 for inference.")
        except Exception as override_exc:
            logger.warning("Could not override n_jobs on loaded model: %s", override_exc)

        logger.info(
            "Applicability model loaded (version=%s) from %s",
            _instance.model_version,
            model_path,
        )
        return _instance
    except Exception as exc:
        logger.error("Failed to load applicability model from '%s': %s", model_path, exc)
        _instance = None
        return None


def get_applicability_model() -> Optional["ApplicabilityModel"]:
    """Return the current singleton, or None if not yet loaded."""
    return _instance


# ---------------------------------------------------------------------------
# Model class
# ---------------------------------------------------------------------------
class ApplicabilityModel:
    """
    Thin wrapper around the joblib-serialised scikit-learn pipeline.

    The pipeline is expected to:
      - Accept a pd.DataFrame with 14 named feature columns
      - Handle NaN values internally via its own imputer step
      - Expose predict_proba() returning shape (1, 2)  [NOT_APPLICABLE, APPLICABLE]
    """

    # Number of features the model expects
    N_FEATURES: int = 14

    def __init__(self, model_path: str, metadata_path: str) -> None:
        self.pipeline = joblib.load(model_path)
        self._pin_single_thread()

        with open(metadata_path, "r", encoding="utf-8") as fh:
            metadata = json.load(fh)

        self.model_version: str = metadata.get("model_version", "unknown")
        self._metadata = metadata

    # ------------------------------------------------------------------
    # OpenMP safety
    # ------------------------------------------------------------------
    def _pin_single_thread(self) -> None:
        """
        Force the LightGBM estimator inside the pipeline to n_jobs=1.

        Why this is not optional: torch, scikit-learn, faiss and lightgbm each
        ship their own copy of libomp, so four independent OpenMP runtimes end
        up mapped into one process. When LightGBM predicts with its default
        n_jobs=None (== all cores) it calls __kmpc_fork_call to spin up a
        worker team, and that team collides with another runtime's thread
        state -- a hard SIGSEGV inside __kmp_suspend_initialize_thread, which
        no try/except in predict() can catch.

        Setting n_jobs=1 means LightGBM never forks a parallel region, so there
        is no team for a foreign runtime to corrupt. Verified: n_jobs=None
        segfaults (exit 139), n_jobs=1 predicts cleanly. Inference here is one
        row at a time, so there is nothing to parallelise anyway -- and one
        thread also trims RAM on the 512 MB Render box.

        Note that KMP_DUPLICATE_LIB_OK / OMP_NUM_THREADS do NOT cover this:
        the first only silences libomp's load-time duplicate-registration
        abort, and the second is overridden because LightGBM calls
        omp_set_num_threads() itself from its own n_jobs parameter.
        """
        def walk(step):
            """Yield every estimator in the tree (the pipeline nests one deep)."""
            yield step
            for _, inner in getattr(step, "steps", None) or ():
                yield from walk(inner)

        for est in walk(self.pipeline):
            if not type(est).__name__.startswith("LGBM"):
                continue
            try:
                est.set_params(n_jobs=1)
                logger.info("Pinned %s to n_jobs=1 (OpenMP safety).", type(est).__name__)
            except Exception as exc:
                # Never fatal: a model without this knob is still usable, and a
                # crash here would take out the whole recommender at startup.
                logger.warning(
                    "Could not pin %s to a single thread: %s -- prediction may be "
                    "unstable if multiple OpenMP runtimes are loaded.",
                    type(est).__name__, exc,
                )

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def predict(self, features_df: pd.DataFrame) -> dict | list[dict]:
        """
        Run inference on a single-row or multi-row feature DataFrame.

        Parameters
        ----------
        features_df : pd.DataFrame
            Shape (N, 14) produced by build_applicability_features().

        Returns
        -------
        dict or list[dict] with keys:
            applicability_score       float in [0, 1]  (P(APPLICABLE))
            applicability_class       "APPLICABLE" | "NOT_APPLICABLE"
            model_version             str
            feature_coverage          float in [0, 1]  (fraction of non-NaN features)

        On any exception the dict contains applicability_class = "UNAVAILABLE"
        and applicability_score = None.
        """
        is_single = len(features_df) == 1
        try:
            probas = self.pipeline.predict_proba(features_df)  # shape (N, 2)
            results = []

            for i in range(len(features_df)):
                # Feature coverage: fraction of columns that have at least one non-NaN value for this row
                row_na = features_df.iloc[i].isna().sum()
                feature_coverage = round((self.N_FEATURES - int(row_na)) / self.N_FEATURES, 3)

                applicability_score = round(float(probas[i][1]), 4)
                applicability_class = (
                    "APPLICABLE" if applicability_score >= 0.5 else "NOT_APPLICABLE"
                )

                results.append({
                    "applicability_score": applicability_score,
                    "applicability_class": applicability_class,
                    "model_version": self.model_version,
                    "feature_coverage": feature_coverage,
                })

            return results[0] if is_single else results

        except Exception as exc:
            logger.error(
                "ApplicabilityModel.predict() failed: %s -- returning UNAVAILABLE.", exc
            )
            fallback = {
                "applicability_score": None,
                "applicability_class": "UNAVAILABLE",
                "model_version": self.model_version,
                "feature_coverage": 0.0,
            }
            return fallback if is_single else [fallback] * len(features_df)
