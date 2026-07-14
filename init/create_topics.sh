#!/bin/bash

# Wait for Kafka to be ready
echo "Waiting for Kafka to be ready..."
sleep 30

KAFKA_CONTAINER="${KAFKA_CONTAINER:-stockgod-kafka-1}"

create_topic() {
  docker exec "$KAFKA_CONTAINER" kafka-topics --create \
    --bootstrap-server localhost:9092 \
    --topic "$1" \
    --partitions 3 \
    --replication-factor 1 \
    --if-not-exists
}

create_topic raw_social_data
create_topic aggregated_scores

echo "Kafka topics created successfully!"
