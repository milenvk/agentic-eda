# Build with the repository root as context, so the shared kernel can be copied in.
FROM python:3.13-slim
WORKDIR /app
COPY lib lib
COPY components/front_desk component
RUN pip install --no-cache-dir ./lib "./component[dev]"
CMD ["uvicorn", "front_desk.app:app", "--host", "0.0.0.0", "--port", "8000"]
