# Build with the repository root as context, so the shared kernel can be copied in.
FROM python:3.13-slim
WORKDIR /app
COPY lib lib
COPY components/itinerary_planner_minimal component
RUN pip install --no-cache-dir ./lib "./component[dev]"
CMD ["python", "-m", "itinerary_planner_minimal"]
