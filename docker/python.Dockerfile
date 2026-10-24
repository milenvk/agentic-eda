# The Python image with the library, the application's shared code, and the suppliers'
# shared world: runs demo scripts, chapter-level tests, and the shared packages' own suites. Component images are self-contained instead; see
# each component's Dockerfile.
FROM python:3.14-slim
WORKDIR /app
COPY lib lib
RUN pip install --no-cache-dir "./lib/agentic_eda[dev]" "./lib/travel_agency[dev]" "./lib/supplier_world[dev]"
CMD ["python"]
