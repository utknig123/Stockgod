FROM apache/spark-py:latest

USER root

# Install Python dependencies and system packages
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set Python path and Spark environment
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYSPARK_PYTHON=python3
ENV PYSPARK_DRIVER_PYTHON=python3
ENV SPARK_HOME=/opt/spark

# Create checkpoint directories
RUN mkdir -p /tmp/checkpoint /tmp/checkpoint_aggregated /tmp/checkpoint_posts /tmp/checkpoint_scores

CMD ["python3", "streaming_pipeline.py"]

