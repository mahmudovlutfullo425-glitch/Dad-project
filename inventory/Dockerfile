FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Compile the proto into /app so the generated `import inventory_pb2`
# in inventory_pb2_grpc.py resolves naturally against sys.path[0].
COPY proto/ proto/
RUN python -m grpc_tools.protoc -I proto \
    --python_out=. \
    --grpc_python_out=. \
    proto/inventory.proto

COPY app/ app/

EXPOSE 50051

CMD ["python", "-m", "app.server"]
