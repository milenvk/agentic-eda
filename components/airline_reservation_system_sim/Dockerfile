# Build with the repository root as context, so the suppliers' shared world can be copied in.
# A simulator stands for a system outside the agency and installs nothing of the agency's.
FROM python:3.14-slim
WORKDIR /app
COPY lib/supplier_world lib/supplier_world
COPY components/airline_reservation_system_sim component
RUN pip install --no-cache-dir ./lib/supplier_world "./component[dev]"
WORKDIR /app/component
# Healthy once the port answers, so a dependant can wait for it with `service_healthy`.
HEALTHCHECK --interval=2s --timeout=2s --retries=15 \
    CMD python -c "import socket; socket.create_connection(('localhost', 8000), 1)"
CMD ["uvicorn", "airline_reservation_system_sim.app:app", "--host", "0.0.0.0", "--port", "8000"]
