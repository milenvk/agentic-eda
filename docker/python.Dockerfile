# The kernel-equipped Python image: runs demo scripts, chapter-level tests, and
# the kernel's own test suite. Component images are self-contained instead — see
# each component's Dockerfile.
FROM python:3.13-slim
WORKDIR /app
COPY lib lib
RUN pip install --no-cache-dir "./lib[dev]"
CMD ["python"]
