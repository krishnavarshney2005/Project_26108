"""
kartikey/analysis/llm_client.py

Thin wrapper around the Google Gemini API (google-genai SDK).

Responsibilities:
  - Configure the Gemini client from settings
  - Model selection with a working fallback chain
  - Retry logic for transient errors (429 rate limit, 503 overload)
  - Consistent JSON output extraction from model responses
  - Structured error reporting so callers don't need to handle SDK internals

Model selection rationale:
  - Primary:  settings.gemini_model (default gemini-3.6-flash) — configurable
    via the GEMINI_MODEL env var, so a deprecation needs no code change.
  - Fallback: gemini-3.6-flash-lite, then the *-latest aliases.
  - Selection happens against the *real* request, not a throwaway "ping": the
    first model that answers wins and is cached for the rest of the process.
    An earlier version probed each model first, which cost an extra API call per
    process and — worse — made every call depend on a second, unrelated call
    succeeding. A transient 503 on the probe took the whole LLM path down with
    zero retries, because the probe ran *before* the retry loop.

Why we use JSON mode:
  - Requirement extraction returns structured data (list of Requirement objects)
  - Plain text output is unpredictable; JSON mode forces schema compliance
  - We still validate and parse the output ourselves rather than trusting the model

Security note:
  - Tender documents are untrusted input.
  - The prompt explicitly frames the document as data-to-analyse, not instructions.
  - We never tell the model to "execute" or "run" anything from the document.
"""

from __future__ import annotations

import json
import time
from typing import Any

from shared.config import settings
from shared.utils import AnalysisError, get_logger

logger = get_logger(__name__)

# Models tried in order — first one available wins.
# The configured model (settings.gemini_model / GEMINI_MODEL env var) is always
# probed first; the rest act as a fallback chain if Google deprecates it.
# This list is ordered: stable → lite → preview.
_MODEL_FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]

# Configured model first, then the fallbacks (de-duplicated, order preserved).
_MODEL_PRIORITY = list(
    dict.fromkeys(
        [m for m in [settings.gemini_model] if m] + _MODEL_FALLBACKS
    )
)

# Retry settings for transient errors.
# One "sweep" tries every candidate model once; sleeps happen between sweeps,
# never between models. A model that is overloaded right now is best abandoned
# immediately for the next one — sleeping on it just adds latency.
_MAX_RETRIES = 3
_RETRY_WAIT_SECONDS = 2.0


class GeminiClient:
    """
    Gemini API client with automatic model selection, retry logic, and API key rotation.

    Usage:
        client = GeminiClient()
        result = await client.generate_json(prompt, system_prompt)
    """

    def __init__(self) -> None:
        # Collect all available API keys for rotation (load balancing across team members)
        raw_keys = [
            settings.google_api_key,
            settings.google_api_key_2,
            settings.google_api_key_3,
        ]
        self._api_keys = [k.strip() for k in raw_keys if k and k.strip()]
        if not self._api_keys:
            raise AnalysisError(
                "GOOGLE_API_KEY is not set. Add it to backend/.env.",
                code="LLM_NOT_CONFIGURED",
            )
        self._key_index = 0
        self._clients: dict[str, Any] = {}
        self._working_model: str | None = None

    @property
    def _api_key(self) -> str:
        """Current API key — rotates on each call to spread quota usage."""
        key = self._api_keys[self._key_index % len(self._api_keys)]
        self._key_index += 1
        return key

    def _get_client(self, api_key: str | None = None):
        """Return (or lazily create) a Gemini client for the given key."""
        key = api_key or self._api_keys[0]
        if key not in self._clients:
            try:
                from google import genai
                self._clients[key] = genai.Client(api_key=key)
            except ImportError as exc:
                raise AnalysisError(
                    "google-genai is not installed. Run: pip install google-genai",
                    code="LLM_NOT_CONFIGURED",
                ) from exc
        return self._clients[key]

    def _candidate_models(self) -> list[str]:
        """
        Models to try for one call, best first.

        A model that has already answered is tried first, but the rest of the
        chain stays available: "worked a minute ago" does not mean "is not
        overloaded right now".
        """
        if not self._working_model:
            return list(_MODEL_PRIORITY)
        return list(dict.fromkeys([self._working_model] + _MODEL_PRIORITY))

    def _resolve_model(self) -> str:
        """
        Return a model name that responds, probing the priority list in order.

        Only needed by callers that build their own `generate_content` call and
        so need a model name up front — currently the image-OCR route in
        `kartikey/api/routes/procurement.py`. `generate_json` deliberately does
        not use this; see the module docstring.

        The result is cached, and `generate_json` populates the same cache, so
        in practice this rarely probes at all.
        """
        if self._working_model:
            return self._working_model

        client = self._get_client()
        from google.genai import errors as genai_errors

        quota_exhausted = 0
        for model in _MODEL_PRIORITY:
            try:
                client.models.generate_content(
                    model=model,
                    contents="ping",
                    config={"max_output_tokens": 1},
                )
            except genai_errors.ClientError as e:
                if "404" in str(e) or "NOT_FOUND" in str(e):
                    logger.debug("Model '%s' not available — trying next.", model)
                elif "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    # Free-tier quota is per model, so the next one may be fine.
                    quota_exhausted += 1
                    logger.warning("Model '%s' quota exhausted — trying next.", model)
                else:
                    logger.warning("Model '%s' failed with unexpected error: %s", model, e)
                continue
            except Exception as e:  # noqa: BLE001
                # Covers ServerError (503 "high demand" — transient and specific
                # to one model) and transport failures. These used to escape raw,
                # aborting the whole LLM path on the first overloaded model.
                logger.warning("Model '%s' probe failed: %s", model, e)
                continue

            self._working_model = model
            logger.info("GeminiClient: using model '%s'", model)
            return model

        if quota_exhausted == len(_MODEL_PRIORITY):
            raise AnalysisError(
                "Gemini API quota exhausted on every candidate model. "
                "Free-tier: get a new key at aistudio.google.com.",
                code="LLM_QUOTA_EXHAUSTED",
            )
        raise AnalysisError(
            f"No Gemini model is available. Tried: {_MODEL_PRIORITY}. "
            "Check your API key and model availability at aistudio.google.com.",
            code="LLM_NO_MODEL_AVAILABLE",
        )

    def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,  # low temp for structured extraction
        response_schema: Any | None = None,
    ) -> dict | list:
        """
        Call Gemini and return parsed JSON output.

        Parameters
        ----------
        prompt:
            The user-turn prompt containing the document/data to analyse.
        system_prompt:
            System-level instructions (persona, task framing, output format).
        temperature:
            Sampling temperature. Keep low (0.1–0.2) for extraction tasks
            where determinism matters.
        response_schema:
            Optional Pydantic model (or genai schema dict) constraining the
            output shape. When supplied, Gemini enforces the schema server-side,
            so callers get well-formed JSON instead of best-effort prose. We
            still validate the parsed result ourselves — a schema constrains
            shape, not truthfulness.

        Returns
        -------
        dict | list
            Parsed JSON from the model response.

        Raises
        ------
        AnalysisError
            LLM_NOT_CONFIGURED      — API key missing or SDK not installed
            LLM_QUOTA_EXHAUSTED     — out of credits on every candidate model
            LLM_NO_MODEL_AVAILABLE  — no candidate model exists for this key
            LLM_PARSE_ERROR         — model returned non-JSON output
            LLM_CALL_FAILED         — unrecoverable API error after retries
        """
        from google.genai import errors as genai_errors
        from google.genai import types

        # Build contents
        contents = prompt
        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "response_mime_type": "application/json",
            # We never pass tools, so the SDK's automatic-function-calling loop
            # has nothing to do. Disabling it skips a deep copy of the config per
            # call and the "direct use of AFC is not recommended" warning it logs.
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if response_schema is not None:
            config_kwargs["response_schema"] = response_schema

        config = types.GenerateContentConfig(**config_kwargs)

        candidates = self._candidate_models()
        unavailable: set[str] = set()  # 404 — will not appear later in this call
        last_exc: Exception | None = None
        sweep = 0

        for sweep in range(1, _MAX_RETRIES + 1):
            # A fresh key per sweep: free-tier quota is per key, so retrying with
            # the key that just returned 429 would only earn another 429.
            client = self._get_client(self._api_key)

            for model in candidates:
                if model in unavailable:
                    continue
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config,
                    )
                    if self._working_model != model:
                        logger.info("GeminiClient: using model '%s'", model)
                    self._working_model = model
                    raw = response.text.strip() if response.text else ""
                    return _parse_json_response(raw)

                except genai_errors.ClientError as e:
                    last_exc = e
                    text = str(e)
                    if "404" in text or "NOT_FOUND" in text:
                        # The model does not exist for this key — stop asking.
                        unavailable.add(model)
                        logger.debug("Model '%s' not available — trying next.", model)
                        continue
                    if "429" in text or "RESOURCE_EXHAUSTED" in text:
                        # Per-model, per-key quota: a rate-limited flash says
                        # nothing about flash-lite, or about the next key.
                        logger.warning(
                            "Model '%s' quota exhausted (sweep %d/%d) — trying next.",
                            model, sweep, _MAX_RETRIES,
                        )
                        continue
                    # Any other 4xx is a problem with our request, not with the
                    # model. Failing over would burn quota and hide the cause.
                    raise AnalysisError(
                        f"Gemini API client error: {e}",
                        code="LLM_CALL_FAILED",
                    ) from e

                except genai_errors.ServerError as e:
                    # 5xx, typically 503 "this model is experiencing high demand".
                    # Transient and model-specific, so move on immediately rather
                    # than sleeping on a model that is overloaded right now.
                    last_exc = e
                    logger.warning(
                        "Gemini server error on '%s' (sweep %d/%d): %s",
                        model, sweep, _MAX_RETRIES, e,
                    )
                    continue

                except Exception as e:  # noqa: BLE001
                    # Two very different failures land here.
                    last_exc = e
                    logger.warning(
                        "Error calling Gemini on '%s' (sweep %d/%d): %s",
                        model, sweep, _MAX_RETRIES, e,
                    )
                    if isinstance(e, AnalysisError):
                        # Our own parse error: the model answered, just not with
                        # JSON. Another model may well do better.
                        continue
                    # Transport failure (DNS, TLS, proxy, connection reset). The
                    # network is down, not the model — trying the rest of the
                    # chain would just repeat the same failure three more times.
                    break

            if len(unavailable) == len(candidates):
                break  # every model 404'd; more sweeps cannot help
            if sweep < _MAX_RETRIES:
                time.sleep(_RETRY_WAIT_SECONDS * sweep)

        if isinstance(last_exc, AnalysisError):
            # Our own error — usually LLM_PARSE_ERROR. Keep its code instead of
            # flattening everything to LLM_CALL_FAILED.
            raise last_exc
        if last_exc is not None and (
            "429" in str(last_exc) or "RESOURCE_EXHAUSTED" in str(last_exc)
        ):
            raise AnalysisError(
                "Gemini API quota exhausted on every candidate model. "
                "Free-tier: get a new key at aistudio.google.com.",
                code="LLM_QUOTA_EXHAUSTED",
            ) from last_exc
        if unavailable and len(unavailable) == len(candidates):
            raise AnalysisError(
                f"No Gemini model is available. Tried: {candidates}. "
                "Check your API key and model availability at aistudio.google.com.",
                code="LLM_NO_MODEL_AVAILABLE",
            ) from last_exc
        raise AnalysisError(
            f"Gemini call failed after {sweep} sweep(s) over "
            f"{len(candidates)} model(s): {last_exc}",
            code="LLM_CALL_FAILED",
        ) from last_exc


def _parse_json_response(raw: str) -> dict | list:
    """
    Parse JSON from a model response, handling common wrapping patterns.

    Gemini sometimes wraps JSON in markdown code fences even with
    response_mime_type=application/json. We strip those defensively.
    """
    if not raw:
        raise AnalysisError(
            "Model returned an empty response.",
            code="LLM_PARSE_ERROR",
        )

    # Strip markdown code fences if present
    text = raw
    if text.startswith("```"):
        # e.g. ```json\n{...}\n```
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Try to find JSON within the response as last resort
        start = text.find("[")
        if start == -1:
            start = text.find("{")
        if start != -1:
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError:
                pass
        raise AnalysisError(
            f"Model did not return valid JSON. Raw output (first 300 chars): {raw[:300]}",
            code="LLM_PARSE_ERROR",
        ) from exc


# Singleton — lazily created on first use
_client_instance: GeminiClient | None = None


def get_llm_client() -> GeminiClient:
    """Return the shared GeminiClient instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = GeminiClient()
    return _client_instance
