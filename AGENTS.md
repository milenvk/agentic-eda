# Agentic EDA: Agent Rules

The companion code repository for the book *Event-Driven Agentic Architecture*. The
application design is in `design/` (read `design/04_implementation_design.adoc` before
writing any code), and each chapter's runnable demo is in `chapters/chNN/`.

- **This repository is read by the book's readers.** Reader-facing text (READMEs,
  `.env.example`, code comments) follows the book's writing discipline: no em dashes,
  ever (use parentheses, a colon, a comma, or two sentences); no anthropomorphized
  artifacts (an example is located in a directory, not living in one) and no livelihood
  idioms ("earns its keep"); no object relative clauses, with or without the pronoun
  ("rules the map carries" and "the interface that the inversion implies" become "the map's
  rules" and "the interface implied by the inversion"; a relative clause stays only when its
  head noun is the clause's subject, as in "a consumer that dies mid-handler"); an id or a
  value is generated, never minted; shell code blocks contain commands only, with the
  explanation in a prose sentence before the block, because zsh rejects `#` comments pasted
  interactively.
- **The design documents are the authority.** `design/01`-`design/03` fix the
  architecture, workflows, events, and chapter mapping;
  `design/04_implementation_design.adoc` fixes the low-level conventions: the frozen
  `EventBroker` surface, event naming, repository layout, additive evolution, and the
  demo and README conventions. Follow them, and when a change contradicts them, update
  the design doc in the same change or stop and ask.
- **Never commit.** Commits are the author's review checkpoint.
- **Verify with the chapter test gate.** `chapters/chNN/test.sh` runs every suite inside
  its component's own image, with no host Python, no `.env`, and no network.
- **Demos surface messy reality.** Routine-but-alarming output (such as Kafka's
  fresh-start reports) stays visible and is explained in the README, never filtered or
  suppressed.
