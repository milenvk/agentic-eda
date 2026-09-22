# The framework alone, for its own test suite. The application is deliberately absent:
# if the framework ever imported it, the suite would fail here.
FROM python:3.14-slim
WORKDIR /app
COPY lib/agentic_eda lib/agentic_eda
RUN pip install --no-cache-dir "./lib/agentic_eda[dev]"
CMD ["pytest", "lib/agentic_eda/tests", "-q"]
