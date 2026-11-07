# ARGUS reference → Labyrinth

By **Infinitum Corporation®**. `argus.LabyrinthClient` is an opt-in artifact client,
not an observation collector or an automatic exercise-data export. No tracking,
advisory recommendations, human-command rules or existing program behavior changes.

Supply a trusted HTTPS central `/api/labyrinth` endpoint and a token callback
returning a real Cumulus ID/repository credential. Sign in to the authoritative
Cumulus host through its existing passkey/MFA/social/SSO flow. Explicit CID consent
and client paid LBRNTH entitlement are distinct. The central authenticated
`sessionToken()` operation can issue a repository-only 15-minute bearer tied to
the live parent session. Do not put tokens in source, URLs, command histories or
logs; obtain them through trusted runtime credential handling. Native login UI/
credential acquisition is not implemented by this reference library.

The standard-library client exposes `repositories`, `create_repository`, `save`,
`load` and `history`. Save requires expected branch head (null for an empty branch).
Every call pins product `argus`; the server derives org/role from live CID state,
checks plan/consent/membership and namespaces selected artifacts beneath
`products/argus/...`. No field can claim a CID, organization or role.

HTTPS only, no URL credentials/query tokens, no redirects, 10-second timeout,
2-MiB request/response bounds. No new Python dependency. Importing does not send
anything. Tests: `python3 -m unittest discover -s tests -v`; syntax verification:
`python3 -m compileall -q argus sim main.py`. No pre-existing static typecheck
configuration or tests were present in this reference repository.

This is an undeployed PR only: no exercise records copied, no site/Vercel changes,
no production configuration and no merge. The older argus-odin-reference copy
remains untouched, following its canonical-repo notice.
