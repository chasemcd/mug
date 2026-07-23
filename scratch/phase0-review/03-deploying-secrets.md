# 03 — Deploying a study & binding secrets

| Field | Value |
| --- | --- |
| User | Researcher running their own study (the common case); optionally a separate operator on a team |
| Goal | Get a published version live at a URL, with credentials, in one command — no ceremony |
| Backing contract | [API-02](../../docs/architecture/phase-0/api-02/index.md) · [deployment-and-secrets](../../docs/architecture/phase-0/api-02/deployment-and-secrets.md) · secret store [API-20](../../docs/architecture/phase-0/api-20/index.md) |
| Status | ✅ all 5 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## The friction problem (why this was rewritten)

The first draft exposed the platform's internals — `Deployment.create()` →
`new_revision()` → `satisfaction()` → `promote()`, hand-managed `SecretRef`s, a
mandatory author/operator role split — as *user steps*. For the common case (one
researcher running their own study) that's four calls and two roles to do one
thing. **Most studies are driven by a single person; deployment should be one
command.** The guarantees underneath stay; the ceremony goes.

## What the user actually does

### Solo researcher (the default)

```bash
mug deploy cooperative-foraging@2.1 \
    --at https://study.lab.edu \
    --region us-east \
    --secret chat-provider-key=$OPENAI_KEY
# → "v2.1 is live at https://study.lab.edu"
```

or in Python:

```python
study.deploy(
    version="2.1",
    at="https://study.lab.edu",
    region="us-east",
    secrets={"chat-provider-key": os.environ["OPENAI_KEY"]},
)
```

That's it. One call. If something the study needs isn't provided, it fails with a
plain message *before* going live:

```text
Cannot deploy cooperative-foraging@2.1:
  · missing secret: chat-provider-key (needed by: LLM partner)
  · region "eu-west" not allowed by study (allowed: us-east, us-west)
```

There are only two verbs. Bring it up, change its wiring, rotate a key, or bring a
stopped study back — all `mug deploy`. Take it down — `mug stop`. New participants
get any change; anyone mid-session is untouched.

```bash
mug deploy cooperative-foraging@2.1 --secret chat-provider-key=$NEW_KEY   # change wiring / rotate / bring back
mug stop   cooperative-foraging                                           # take it down (no new participants)
```

### Local iteration (optional convenience)

```bash
mug run cooperative-foraging          # publish current git state + deploy locally, in one go
```

## What stays invisible (guarantees, not steps)

Everything the first draft made you *do*, the platform now does *for* you:

| You do nothing; the platform… | Why it still matters |
| --- | --- |
| creates an **immutable deployment record** each time you deploy | you can always see exactly how the study was wired at any moment; a fix can't secretly rewrite history |
| **checks the study's declared needs are met** and refuses to go live if not | "I forgot the API key" is caught before a participant hits a broken study — surfaced as the plain error above, not a report object you call |
| **stores your secret and references it**; the raw value never enters the compiled study, the deployment record, logs, exports, or the browser | credentials can't leak through provenance or the client — a security property, not a filtering step that can regress |
| **pins each visit** to the version+wiring it started on | you can redeploy or rotate mid-study without interrupting or corrupting anyone in progress |
| delivers participants an **allowlisted client view** (endpoints/region only) | the browser structurally cannot receive secrets, server builds, or provider identity |

## Decisions to review

Mark each `Status:` line.

### D03-1 — Deploy is one call; revisions/satisfaction/promotion are hidden
`mug deploy study@version --at … --secret …` (or `study.deploy(...)`) does the whole
thing: it makes an immutable deployment record, verifies the study's needs are met,
and goes live — in one step. The internal objects still exist (for history, team
review, rollback) but are not something a solo user touches.
- **Why it matters:** the common case is one command; the machinery is available underneath but never in the way.
- **Status:** ✅ approved

### D03-2 — One person, one role by default; author/operator split is opt-in
A solo researcher authors, publishes, and deploys with one identity and no mode
switch. Separating "who may deploy" from "who may author" is a **team feature** you
turn on (via API-20 grants), not a step everyone pays for.
- **Why it matters:** removes the two-role friction for the 90% case while still letting a lab restrict production credentials to certain people when it matters.
- **Status:** ✅ approved

### D03-3 — Secrets are passed at deploy time (value or env); the platform stores+references them
You hand the deploy call a value (typically from an env var), and the platform puts
it in the secret store and wires a reference. No separate "register the secret
first" step, no hand-managed `SecretRef`. The value still never touches the study
source, compiled artifact, deployment record, or client.
- **Why it matters:** lowest-friction path that still keeps secrets out of the science and the browser. Passing a raw value to a *runtime* call is fine — it goes to the store, not the study.
- **Open question:** also support pointing at an external secret manager (Vault/AWS) by reference, for labs that don't want the value passing through `mug` at all?
- **Status:** ✅ approved

### D03-4 — The four guarantees stay on, always, invisibly
Immutable deployment record, needs-are-met check, secret isolation, and in-flight
visit pinning are **not optional** and **not user-visible steps** — they always
happen, and only surface when something's wrong (a plain deploy error).
- **Why it matters:** we get the safety/reproducibility properties without the ceremony; the user only ever sees them as a helpful failure, never as busywork.
- **Status:** ✅ approved

### D03-5 — Two verbs total: `deploy` and `stop`
Everything about running a study is one of two commands. **`deploy`** brings it up,
changes its wiring, rotates a key, or brings a stopped study back. **`stop`** takes
it down (no new participants). There is no separate suspend/resume/retire
vocabulary — "stopped" just means "not live," and deploying again brings it back.
New visits get any change; in-flight visits are untouched. Neither verb deletes data
(deletion is separate governance, surface 13).
- **Why it matters:** the operator learns two verbs, not five. The platform still records the underlying availability history internally, but the user never juggles it.
- **Open question:** on rotate, default to follow-current (new value used everywhere going forward) — with pinned-for-reproducibility as an advanced opt-in?
- **Status:** ✅ approved

## Open questions for you

- **`mug run` (publish + deploy in one) for local dev** — useful convenience, or does
  collapsing publish and deploy blur a boundary we want kept sharp even locally?
- **External secret managers** (D03-3): support by-reference to Vault/AWS/etc., or is
  "hand `mug` the value, it stores it" enough for v0?
- **Rotation default** (D03-5): follow-current vs pinned.
- **Where deploy config lives:** all on the command line / call, or a small
  `deploy.toml` per study for repeatable deploys (endpoints, region, secret *names*)?
