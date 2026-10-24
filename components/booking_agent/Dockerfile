# Build with the repository root as context, so the two libraries can be copied in.
FROM python:3.14-slim
WORKDIR /app
COPY lib lib
COPY components/booking_agent component
RUN pip install --no-cache-dir ./lib/agentic_eda ./lib/travel_agency "./component[dev]"
WORKDIR /app/component
ENV COMPONENT_NAME=BookingAgent
CMD ["uvicorn", "booking_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
