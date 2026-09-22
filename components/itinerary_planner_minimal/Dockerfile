# Build with the repository root as context, so the two libraries can be copied in.
FROM python:3.14-slim
WORKDIR /app
COPY lib lib
COPY components/itinerary_planner_minimal component
RUN pip install --no-cache-dir ./lib/agentic_eda ./lib/travel_agency "./component[dev]"
CMD ["python", "-m", "itinerary_planner_minimal"]
