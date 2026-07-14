"""
Kafka service for consuming real-time data
"""
import os
import json
import logging
from kafka import KafkaConsumer
from typing import Callable, Optional

logger = logging.getLogger(__name__)

class KafkaService:
    def __init__(self):
        self.kafka_broker = os.getenv('KAFKA_BROKER', 'localhost:9092')
    
    def create_consumer(self, topic: str, group_id: str = 'api-consumer'):
        """Create a Kafka consumer"""
        return KafkaConsumer(
            topic,
            bootstrap_servers=[self.kafka_broker],
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id=group_id,
            auto_offset_reset='latest',
            enable_auto_commit=True
        )
    
    def consume_messages(self, topic: str, callback: Callable, group_id: Optional[str] = None):
        """Consume messages from a topic"""
        consumer = self.create_consumer(topic, group_id or f'consumer-{topic}')
        
        try:
            for message in consumer:
                callback(message.value)
        except KeyboardInterrupt:
            logger.info("Stopping consumer...")
        finally:
            consumer.close()

