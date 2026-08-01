"""What this session's athlete shares with the coach.

The athlete picks in the iOS app which categories of health data the coach may
read. The backend stores that set (`/api/me/data-consent`) and filters the data
it returns; this module is the other half — deciding which tools are advertised
at all.

**Unadvertised, never refused.** A tool that is listed and then errors produces
a coach that retries, apologises, and tells the athlete to go enable sleep
tracking — reintroducing in conversation exactly the nagging the app's own
surfaces were built to avoid. A tool that was never listed is simply never
reasoned about.

Consent is resolved per identity (the caller's bearer token), because this
server is multi-user by token passthrough: two sessions on the same process can
belong to different athletes with different choices.
"""

import hashlib
import logging
import time

from app.services.api_client import client

logger = logging.getLogger(__name__)

TRAINING = "training"
RECOVERY = "recovery"
BODY = "body"
ACTIVITY = "activity"
NUTRITION = "nutrition"

ALL_DOMAINS = frozenset({TRAINING, RECOVERY, BODY, ACTIVITY, NUTRITION})

# Domains carried by columns of the daily-metrics row.
METRIC_DOMAINS = (RECOVERY, BODY, ACTIVITY)

# Tool → the domains that justify advertising it; ANY of them is enough.
# Everything absent from this map is `training` (workouts, queue, actions,
# feedback, plans, notes, coaching) and is always available: an athlete who
# shares nothing else still shares workouts, or there is no history to coach
# from. `get_health_metrics` spans three domains because they are columns of
# one row — the backend then drops the unshared columns from the payload.
TOOL_DOMAINS: dict[str, tuple[str, ...]] = {
    "get_health_metrics": METRIC_DOMAINS,
    "get_nutrition": (NUTRITION,),
    "get_nutrition_summary": (NUTRITION,),
}

_TTL_SECONDS = 60.0
_MAX_ENTRIES = 64
_cache: dict[str, tuple[float, frozenset[str]]] = {}


def _identity_key() -> str:
    """A stable, non-reversible handle for the caller's credential."""
    try:
        return hashlib.sha256(client.resolve_auth().encode()).hexdigest()[:16]
    except Exception:
        return "unresolved"


async def shared_domains() -> frozenset[str]:
    """The caller's shared set, cached briefly.

    Called on every tools/list and initialize, so it must not add a round trip
    to each one — but it must also not pin a stale answer for long, since a
    consent change should take effect on the next session.

    On a lookup failure, the last known good answer is reused; with none, every
    domain is assumed. That direction is deliberate: in a real outage every
    data tool fails anyway, so there is nothing to disclose, whereas failing
    closed would silently strip a working coach of its context on a blip.
    """
    key = _identity_key()
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]

    try:
        payload = await client.get_data_consent()
        domains = frozenset(payload.get("domains") or ALL_DOMAINS)
    except Exception as exc:
        if cached:
            logger.warning(f"Consent lookup failed, reusing last known set: {exc}")
            return cached[1]
        logger.warning(f"Consent lookup failed with nothing cached, assuming all domains: {exc}")
        return ALL_DOMAINS

    if len(_cache) >= _MAX_ENTRIES and key not in _cache:
        _cache.clear()
    _cache[key] = (now, domains)
    return domains


def tool_is_shared(tool_name: str, domains: frozenset[str]) -> bool:
    """Whether a tool should be advertised to a caller sharing `domains`."""
    required = _required_domains(tool_name)
    return required is None or any(d in domains for d in required)


def _required_domains(tool_name: str) -> tuple[str, ...] | None:
    # Matched on the suffix as well as the whole name, so mounting a router
    # under a prefix later can't silently turn the filter into a no-op.
    for name, domains in TOOL_DOMAINS.items():
        if tool_name == name or tool_name.endswith(f"_{name}"):
            return domains
    return None
