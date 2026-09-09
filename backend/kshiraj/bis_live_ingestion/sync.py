"""Low-volume live BIS metadata synchronization into the existing StandardsStore."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from kshiraj.knowledge.standards_store import StandardsStore

from .adapters.bis_client import BISClient
from .normalizer import normalize_designation, normalize_standard


@dataclass
class SyncResult:
    requested: str
    matched_designation: str | None = None
    standard_id: str | None = None
    changed: bool = False
    amendment_count: int = 0
    supersedes: str | None = None
    evidence: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BISSyncService:
    """Fetch one exact designation, normalize it, and upsert it into StandardsStore."""

    def __init__(self, client: BISClient, standards_store: StandardsStore) -> None:
        self.client = client
        self.standards_store = standards_store
        self._fingerprints: dict[str, str] = {}

    @staticmethod
    def _fingerprint(detail: dict[str, Any], amendments: list[dict[str, Any]]) -> str:
        canonical = json.dumps(
            {"detail": detail, "amendments": amendments},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def sync_designation(self, designation: str) -> SyncResult:
        requested = normalize_designation(designation)
        try:
            candidates = self.client.search_standards(requested)
            exact = [
                item for item in candidates
                if normalize_designation(str(item.get("standardNumber") or "")) == requested
            ]
            if len(exact) != 1:
                return SyncResult(
                    requested=requested,
                    errors=[
                        f"Expected exactly one exact BIS search candidate for {requested!r}; got {len(exact)}"
                    ],
                )

            candidate = exact[0]
            encoded_id = candidate.get("standardEncId")
            if not encoded_id:
                return SyncResult(requested=requested, errors=["Exact BIS result lacked standardEncId"])

            detail = self.client.get_standard_details(str(encoded_id))
            standard_id = detail.get("standardId") or detail.get("rowStandardId")
            if standard_id is None:
                return SyncResult(requested=requested, errors=["BIS detail lacked standardId"])

            amendments = self.client.get_amendments(standard_id)
            fingerprint = self._fingerprint(detail, amendments)
            previous = self._fingerprints.get(requested)
            std, evidence = normalize_standard(
                detail,
                amendments,
                source_url=self.client.config.portal_url,
            )

            existing = next(
                (
                    s for s in self.standards_store.list_all()
                    if normalize_designation(s.designation) == requested
                ),
                None,
            )
            if existing is not None:
                existing.status = std.status
                existing.amendments = std.amendments
                existing.reaffirmation_year = std.reaffirmation_year
                existing.withdrawal_date = std.withdrawal_date
                existing.retrieved_at = std.retrieved_at
                # Only overwrite superseded_by if BIS provides a definitive replacement
                if std.superseded_by:
                    existing.superseded_by = std.superseded_by
                self.standards_store.upsert(existing)
            else:
                self.standards_store.upsert(std)
            self._fingerprints[requested] = fingerprint

            return SyncResult(
                requested=requested,
                matched_designation=std.designation,
                standard_id=str(standard_id),
                changed=previous != fingerprint,
                amendment_count=len(amendments),
                supersedes=detail.get("superseded_byis") or detail.get("supersededBy") or None,
                evidence=evidence,
            )
        except Exception as exc:
            return SyncResult(requested=requested, errors=[str(exc)])

    def sync_many(self, designations: list[str]) -> list[SyncResult]:
        return [self.sync_designation(item) for item in designations]
