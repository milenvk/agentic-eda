# Build with the repository root as context, so the two libraries can be copied in.
FROM python:3.14-slim
WORKDIR /app
COPY lib lib
COPY components/itinerary_planner component
RUN pip install --no-cache-dir ./lib/agentic_eda ./lib/travel_agency "./component[dev]"
WORKDIR /app/component
ENV COMPONENT_NAME=ItineraryPlannerAgent
CMD ["uvicorn", "itinerary_planner.app:app", "--host", "0.0.0.0", "--port", "8000"]
