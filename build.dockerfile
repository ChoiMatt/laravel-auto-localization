FROM python:3.13-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
	libmagic-dev \
	&& rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code to the container
COPY src/ ./src/

# Expose port (change if your FastAPI server uses a different port)
EXPOSE 8000

# Start FastAPI server with gunicorn and uvicorn worker
CMD ["gunicorn", "src.server:app", "--bind", "0.0.0.0:8000", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--timeout", "120"]
