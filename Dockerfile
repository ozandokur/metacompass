# MetaCompass demo: the Streamlit app on port 7860, for Hugging Face Spaces (spec §11.1).
#
#   docker build -t metacompass .
#   docker run -p 7860:7860 metacompass
#
# SPEC-DEVIATION (approved, PROGRESS "Spec sapmaları"): Python 3.13, not 3.11; the pinned
# numpy and scipy need 3.12 or newer, and CI runs 3.13 too.
FROM python:3.13-slim

# Spaces run the container as uid 1000; build as that user so every file the app writes at
# runtime (its quota log, its model cache) lands where it may write.
RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/user/.cache/huggingface
WORKDIR /home/user/app

# Dependencies first, so a code change does not reinstall them. requirements.txt pins the
# +cpu torch build and carries the PyTorch CPU index: the default wheel would pull CUDA and
# several GB with it.
COPY --chown=user requirements.txt .
RUN pip install --user -r requirements.txt

COPY --chown=user . .
# Editable, like CI: config.PROJECT_ROOT is derived from the source location, so the package
# has to run from this folder, not from site-packages.
RUN pip install --user --no-deps -e .

# Data from seed 42, the embedding model, and the document embeddings, all at build time.
# Deterministic and without any LLM call.
RUN python scripts/warm_up.py

EXPOSE 7860
# No model key is baked in: free text stays off unless the Space's secrets provide one.
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port", "7860", "--server.address", "0.0.0.0", "--server.headless", "true"]
