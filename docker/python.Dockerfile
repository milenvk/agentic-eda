# The Python image with both libraries: runs demo scripts, chapter-level tests, and the
# application library's own test suite. Component images are self-contained instead; see
# each component's Dockerfile.
FROM python:3.14-slim
WORKDIR /app
COPY lib lib
RUN pip install --no-cache-dir "./lib/agentic_eda[dev]" "./lib/travel_agency[dev]"
CMD ["python"]
