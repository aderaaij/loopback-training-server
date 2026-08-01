"""Per-domain data consent — which categories of health data the coach sees.

The athlete picks in the iOS app which categories the coaching LLM may read;
the app PUTs the whole set to `/api/me/data-consent` on every launch and on
every change. This module holds the vocabulary, how a reported set is
normalised, and the map from domain to the daily-metrics columns it governs.

Two things are worth knowing before changing anything here:

**The wire strings are API surface**, shared with `DataDomains.wireValue` in
the app. Renaming one silently revokes a domain, because the server stops
recognising what the app sends.

**`recovery`, `body` and `activity` are not separate tables** — they are
columns of the same daily-metrics row, so a read returning a whole row
discloses all three at once. That makes the column map below the load-bearing
half of this file, not documentation. `test_data_consent.py` asserts it stays
exhaustive against `HealthMetricsRead`, so a metric column added without a
domain fails a test rather than quietly escaping the filter.

Scope of the boundary: this shapes what the *coach* is handed, not who may
read the data. The athlete's own dashboard uses the same token and is
deliberately unfiltered — consent is about disclosure to the LLM, and a
token-holder can always call the REST API directly.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Iterable

from fastapi import Depends, HTTPException, Request, status

from app.auth import CurrentUser

TRAINING = "training"
RECOVERY = "recovery"
BODY = "body"
ACTIVITY = "activity"
NUTRITION = "nutrition"

KNOWN_DOMAINS: tuple[str, ...] = (TRAINING, RECOVERY, BODY, ACTIVITY, NUTRITION)

# A user who has never reported shares everything. An install predating consent
# had no way to restrict anything, so reading that silence as a restriction
# would strip a working coach of its context; and since the app re-pushes on
# every launch, a push that failed (network, or a server without this endpoint)
# self-heals within one launch.
DEFAULT_DOMAINS: list[str] = list(KNOWN_DOMAINS)

# Columns of `daily_health_metrics`, by the domain that governs them.
DOMAIN_METRIC_FIELDS: dict[str, frozenset[str]] = {
    RECOVERY: frozenset(
        {"sleep_duration", "sleep_stages", "resting_heart_rate", "hrv_sdnn", "respiratory_rate", "spo2"}
    ),
    BODY: frozenset({"weight", "vo2_max", "body_fat_percentage", "lean_body_mass"}),
    ACTIVITY: frozenset({"steps", "active_energy_burned", "basal_energy_burned"}),
}

# Bookkeeping, not health content — present whatever the athlete shares.
UNGATED_METRIC_FIELDS = frozenset({"date", "created_at", "updated_at"})

# The domains a daily-metrics row can carry. Reading one needs at least one.
METRIC_DOMAINS: tuple[str, ...] = (RECOVERY, BODY, ACTIVITY)

_MAX_DOMAINS = 20
_MAX_DOMAIN_LENGTH = 32


def normalize(domains: Iterable[str]) -> list[str]:
    """Canonicalise a reported set.

    `training` is forced in: an athlete who shares nothing else still shares
    workouts, because without them there is no training history to coach from.

    Unknown strings are KEPT rather than dropped or rejected. A newer app may
    report a domain this server has not learned yet, and rejecting it would
    break consent pushes for every user on an older server; dropping it would
    lose the athlete's choice on the next upgrade. Unknown values are filtered
    at *use* time (`allows()` only ever answers about known domains), never at
    storage time. Junk is bounded by length and count so the column can't be
    used as free storage.
    """
    out: list[str] = [TRAINING]
    for raw in domains:
        value = (raw or "").strip()
        if not value or len(value) > _MAX_DOMAIN_LENGTH or value in out:
            continue
        out.append(value)
        if len(out) >= _MAX_DOMAINS:
            break
    return out


def metric_fields_for(domains: Iterable[str]) -> frozenset[str]:
    """The `daily_health_metrics` fields a caller with these domains may see."""
    allowed = set(UNGATED_METRIC_FIELDS)
    shared = set(domains)
    for domain, fields in DOMAIN_METRIC_FIELDS.items():
        if domain in shared:
            allowed |= fields
    return frozenset(allowed)


# ── request scoping ─────────────────────────────────────────────────────────
#
# The MCP sends this header on every request it makes on the athlete's behalf,
# centrally, so a newly added tool is filtered without anyone remembering to
# opt it in. Its absence means "the athlete themself is asking" (the dashboard,
# the iOS app), which is never filtered.
CONSENT_SCOPE_HEADER = "X-Consent-Scope"


@dataclass(frozen=True)
class ConsentScope:
    """Whether this request is consent-scoped, and to what."""

    applied: bool
    domains: frozenset[str]

    def allows(self, domain: str) -> bool:
        return not self.applied or domain in self.domains

    def require(self, *domains: str) -> None:
        """403 unless at least one of `domains` is shared.

        The message says *not shared*, never *not recorded*. A coach told the
        data is missing goes on to ask the athlete to start tracking it —
        reintroducing in conversation exactly the nagging the app's own
        surfaces exist to avoid.
        """
        if any(self.allows(d) for d in domains):
            return
        names = " or ".join(f"'{d}'" for d in domains)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"The athlete does not share {names} data with the coach. This is a "
                "sharing setting, not missing data — do not ask them to start tracking it."
            ),
        )


def get_consent_scope(request: Request, user: CurrentUser) -> ConsentScope:
    # Any non-empty value scopes the request: an unrecognised scope must not be
    # the one that turns filtering off.
    applied = bool(request.headers.get(CONSENT_SCOPE_HEADER, "").strip())
    return ConsentScope(applied=applied, domains=frozenset(user.data_consent or DEFAULT_DOMAINS))


CurrentConsent = Annotated[ConsentScope, Depends(get_consent_scope)]


def consent_state(user) -> tuple[list[str], datetime | None, datetime | None]:
    """The stored set plus both timestamps, for echoing back.

    Two stamps, because one cannot answer both questions. The app pushes on
    every launch, so a single "updated" column either means "last launch"
    (useless for spotting a real change) or, if written only on change, stays
    NULL for an athlete whose choice happens to equal the default — making
    "never reported" indistinguishable from "reported, unchanged", which is the
    one thing worth surfacing.
    """
    return (
        list(user.data_consent or DEFAULT_DOMAINS),
        user.data_consent_updated_at,
        user.data_consent_reported_at,
    )
