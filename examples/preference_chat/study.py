"""The study both preference-chat examples run. One study, two backends.

Consent, instructions, the conversation, a short survey about it, and a debrief. The
conversation is written into the list beside the forms and the pages, because that is
what it is: `Chat("counsel", Model(agent))`. What makes it unusual is one keyword --
`elicit` turns each turn into a judgement.

Neither `ollama.py` nor `anthropic.py` changes anything here. They differ in the
model the conversation runs on and in where its credential comes from, which is the
comparison worth showing: **a preference study is not tied to a provider.**
"""

from __future__ import annotations

from examples.preference_chat.agent import GREETING, Counsellor, elicitation
from mug.authoring import LLMAgent
from mug.content import Chat, Choice, Form, Likert, Model, Page, Study, Text
from mug.providers.runtime import ProviderAdapter, SecretResolver

INSTRUCTIONS = """
# Talk it through

You will have a short conversation with an AI assistant about a decision you are
weighing up. Anything will do -- a job, a purchase, a trip, a difficult message you
have to send.

**On each turn you will see two possible replies.** Read both, then:

1. Choose the one you would rather have had.
2. Say how the two compare on a few points.

The conversation carries on from the reply you chose. There are no right answers:
we want to know which reply *you* preferred, not which one is correct.

You can end the conversation whenever you feel finished.
"""

DEBRIEF = """
# Thank you

Both replies you saw on each turn came from the same assistant, asked the same
question twice. Which of them appeared on the left was decided for you and shuffled,
so the side a reply was on tells us nothing.

The replies you did not choose were kept as well. Together, the pairs are the shape
that preference-tuning a model reads.
"""


def preference_chat_study(
    agent: LLMAgent | None = None,
    *,
    adapter: ProviderAdapter | None = None,
    resolve_secret: SecretResolver | None = None,
) -> Study:
    """Return the ordered activities one participant walks through.

    ``agent`` is the model the participant talks to. With none, the shared
    ``Counsellor`` runs, which is what makes the two entry points one study: each
    passes its own subclass and changes nothing else here.

    ``resolve_secret`` is how a credential reaches the provider, and it is a function
    rather than a string on purpose: the value is read at call time and goes into one
    request header. It is never in the study, in a record, or in the compiled bundle.
    A local runner passes none.

    ``adapter`` is only for an endpoint that is not the provider's default -- a
    self-hosted proxy, or a runner on another host. With none, the adapter follows from
    the agent's declared provider.
    """
    return Study(
        Form(
            "consent",
            Choice(
                "agree",
                "I have read the information sheet and agree to take part.",
                ["yes", "no"],
            ),
            Choice(
                "data-sharing",
                "I agree that my anonymised conversation may be shared with other"
                " researchers.",
                ["yes", "no"],
            ),
        ),
        Page("instructions", INSTRUCTIONS),
        # The conversation, written where it happens. ``speaker`` is a ``Model`` and
        # nothing else: the provider adapter follows from the agent's declared
        # provider, and the pinned build and the recorded actor are derived at the
        # mount from the channel and the agent's own key -- so this study writes no
        # identifier anywhere.
        Chat(
            "counsel",
            Model(
                agent or Counsellor(),
                adapter=adapter,
                resolve_secret=resolve_secret,
            ),
            greeting=GREETING,
            elicit=elicitation(),
            # A conversation has to end for the participant to reach the survey, and
            # a participant who never says so still has to get there.
            max_messages=24,
        ),
        Form(
            "post-survey",
            Likert("useful", "How useful was the conversation?", scale=7),
            Likert(
                "easy-to-judge",
                "How easy was it to choose between the two replies?",
                scale=7,
            ),
            Text(
                "what-mattered",
                "What were you looking for when you chose between them? (optional)",
                required=False,
            ),
        ),
        Page("debrief", DEBRIEF),
    )


__all__ = ["preference_chat_study"]
