---
title: MetaCompass
emoji: 🧭
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: A BI metadata agent that knows when to abstain (synthetic data)
---

# MetaCompass

A tool-using agent that answers ownership, lineage and change-impact questions about the BI
metadata of **Northwind Motors, a fictional company. All data is synthetic.**

- **Try a question** in the sidebar: eight prepared questions answer at once, each with the
  full agent trace, from answers recorded with the frozen configuration.
- **Ask your own questions** by running the app locally with your own Google AI Studio key
  (see "Run it locally" in the source repository). This Space has no model key on purpose:
  the free tier's daily quota belongs to the evaluation, and visitors would use it up.
- The measured accuracy, the ablations and the reading rules written before the test run
  are in `eval/results.md` of the source repository.

<!-- This file becomes the Space's README.md when the repository is pushed to the Space
(spec §11, phase 8). The YAML block above is what Hugging Face reads: `sdk: docker` builds
the Dockerfile, and `app_port: 7860` is where the Streamlit app listens. -->
