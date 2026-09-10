"""
ai-engine/src/embedding.py

Generates and normalizes sentence embeddings using SentenceTransformers.

Key fix: embeddings are L2-normalized before returning so that inner-product
search (IndexFlatIP in FAISS) is equivalent to cosine similarity. This means
similarity scores are true cosine similarities in [0, 1] rather than the
broken `1 - dist/2` approximation.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # deferred: avoids loading torch at import time
        logger.info("Loading SentenceTransformer model '%s'...", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def generate_embeddings(text):
    """
    Generate L2-normalised embeddings for the given text(s).

    Returns
    -------
    np.ndarray
        - 1-D array of shape (dim,) when text is a str
        - 2-D array of shape (n, dim) when text is a list

    Because the returned vectors are unit-norm, inner product == cosine similarity.
    """
    model = _get_model()
    single = isinstance(text, str)
    inputs = [text] if single else text

    raw = model.encode(inputs, convert_to_numpy=True, show_progress_bar=False)

    # L2-normalise so inner product becomes cosine similarity
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)   # avoid division by zero
    normalised = (raw / norms).astype("float32")

    return normalised[0] if single else normalised


def embedding_dim():
    """Return the embedding dimension of the loaded model."""
    return _get_model().get_sentence_embedding_dimension()
