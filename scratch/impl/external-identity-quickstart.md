# External identity: admit a recruit without keeping their id

*For anyone who runs a study on a recruitment platform -- Prolific, an OIDC
provider, an institution roster. The platform names each participant with an
external subject id. That id names a real person, so it must never enter the
study data. This is how you admit the same person once, recognize them on return,
and keep only a one-way blinded handle in the record.*

> Status: **built.** `mug/identity/linking.py`, `mug/identity/service.py`
> (`link_identity`), and the boundary `mug/linking.py` are live. A blinded link
> round-trips, and no raw external id enters any record, event, or export.

---

## The whole surface

```python
from mug.linking import (
    provision_identity_link,   # blind an external id and link it to an enrollment
    resolve_enrollment,        # recover the enrollment from the same external id
    blinding_key_from_env,     # read the server key from MUG_IDENTITY_BLINDING_KEY
)

key = blinding_key_from_env() or os.urandom(32)

# A participant arrives from Prolific with PROLIFIC_PID in the launch URL.
link = await provision_identity_link(
    gateway, store,
    researcher=researcher,
    enrollment_id=enrollment_id,
    provider="prolific",
    external_id=prolific_pid,     # used only to derive the handle, never stored
    blinding_key=key,
)
# link.subject_handle is the blinded handle; link.enrollment_id is the enrollment.

# Later, the same participant returns with the same PROLIFIC_PID.
enrollment_id = resolve_enrollment(
    store, provider="prolific", external_id=prolific_pid, blinding_key=key,
)
# -> the enrollment they were linked to, or None if they were never linked.
```

That is the entire author surface. You never build the record, mint the handle, or
touch the gateway; the boundary does it and hands back only the handle and the
enrollment.

---

## Why the external id is safe

`blind_external_id(key, provider, external_id)` maps the id to a `PublicHandle`
with a keyed HMAC-SHA256, truncated to sixteen bytes and rendered as base64url.
The map is:

- **deterministic** -- the same id always blinds to the same handle, so the link
  round-trips and a returning participant is recognized;
- **one-way** -- the handle is a truncated HMAC under the server key, so the id
  cannot be recovered from the handle, and a guesser without the key cannot forge
  another participant's handle;
- **provider-scoped** -- the provider name is mixed in, so the same raw id under
  two providers blinds to two unrelated handles.

The raw id is consumed the moment it arrives, to derive the handle. It is not a
field on the returned value, not a field on the stored record, and not in the
event the link writes. `provision_identity_link` returns a `LinkProvision` that
carries the handle and the enrollment -- never the id.

---

## The server key

The key is a server secret, resolved by name at the boundary, exactly like the
return-link key. Set `MUG_IDENTITY_BLINDING_KEY` to a long random secret in a
deployment, and a blinded handle stays stable across a restart -- a returning
participant is recognized even after the server has restarted. Leave it unset and
a fresh per-process key is used, so the links do not survive a restart. The
blinding function never reads the environment itself and never logs the id.

---

## What it is under the hood

The link is a handle-keyed token, like a launch ticket: it has no revision, and
its key is the blinded handle. So a second link of the same external id (which
blinds to the same handle) redeems to the same record with no second effect, and
`resolve_enrollment` reads it back by that handle. The record is a frozen
`mug.api-03.external-identity-link` -- the same schema serves as its stored state
and its receipt result, so the runtime adds no new schema. The one additive
platform change is `Gateway.mint(..., handle=...)`, which lets the boundary key a
token by its own deterministic handle instead of a gateway-minted one.
