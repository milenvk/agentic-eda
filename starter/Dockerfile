# Build with the repository root as context, so the framework can be copied in.
# Outside this repository, see "Taking it with you" in README.md.
FROM python:3.14-slim
WORKDIR /app
COPY lib/agentic_eda lib/agentic_eda
COPY starter starter
RUN pip install --no-cache-dir ./lib/agentic_eda "./starter[dev]"
WORKDIR /app/starter
CMD ["uvicorn", "review_triage.app:app", "--host", "0.0.0.0", "--port", "8000"]
