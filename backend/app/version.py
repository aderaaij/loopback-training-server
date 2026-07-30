"""Single source of truth for the server version.

pyproject.toml derives its version from this file (hatchling), and the API
surfaces it at /api/health and /api/admin/system. Bump it when cutting a
release — see README "Releases & upgrading".
"""

__version__ = "0.1.9"
