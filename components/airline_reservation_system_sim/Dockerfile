# Build with the repository root as context, so the two libraries can be copied in.
FROM python:3.14-slim
WORKDIR /app
COPY lib lib
COPY components/airline_reservation_system_sim component
RUN pip install --no-cache-dir ./lib/agentic_eda ./lib/travel_agency "./component[dev]"
WORKDIR /app/component
# Healthy once the port answers, so a dependant can wait for it with `service_healthy`.
HEALTHCHECK --interval=2s --timeout=2s --retries=15 \
    CMD python -c "import socket; socket.create_connection(('localhost', 8000), 1)"
CMD ["uvicorn", "airline_reservation_system_sim.app:app", "--host", "0.0.0.0", "--port", "8000"]
