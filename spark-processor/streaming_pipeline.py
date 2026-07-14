"""
PySpark Structured Streaming pipeline for sentiment analysis
"""
import os
import json
import logging
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.types import *
import psycopg2
from sentiment_analyzer import SentimentAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connections
POSTGRES_URL = os.getenv('DATABASE_URL', 'postgresql://admin:admin123@localhost:5432/sentiment_db')
MONGODB_URL = os.getenv('MONGODB_URL', 'mongodb://admin:admin123@localhost:27017')
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'localhost:9092')

# Run Spark in local mode by default: the ML/DB dependencies (transformers,
# torch, psycopg2) are installed in THIS container, not on the spark-worker
# nodes, so submitting to the cluster would fail with ModuleNotFoundError.
SPARK_MASTER = os.getenv('SPARK_MASTER', 'local[*]')

builder = SparkSession.builder \
    .appName("IPO-Sentiment-Streaming") \
    .master(SPARK_MASTER) \
    .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.4.0") \
    .config("spark.sql.streaming.checkpointLocation", "/tmp/checkpoint") \
    .config("spark.sql.adaptive.enabled", "true") \
    .config("spark.sql.adaptive.coalescePartitions.enabled", "true") \
    .config("spark.sql.shuffle.partitions", "4")

if SPARK_MASTER.startswith("spark://"):
    builder = builder \
        .config("spark.driver.host", "spark-processor") \
        .config("spark.driver.bindAddress", "0.0.0.0")

spark = builder.getOrCreate()

spark.sparkContext.setLogLevel("WARN")

# Initialize sentiment analyzer
sentiment_analyzer = SentimentAnalyzer()

# Define schema for raw social data
raw_schema = StructType([
    StructField("post_id", StringType(), True),
    StructField("platform", StringType(), True),
    StructField("company_symbol", StringType(), True),
    StructField("company_name", StringType(), True),
    StructField("content", StringType(), True),
    StructField("original_content", StringType(), True),
    StructField("author", StringType(), True),
    StructField("timestamp", StringType(), True),
    StructField("url", StringType(), True),
    StructField("engagement_count", IntegerType(), True),
    StructField("hashtags", ArrayType(StringType()), True),
    StructField("mentions", ArrayType(StringType()), True),
    StructField("scraped_at", StringType(), True)
])

_company_id_cache = {}

def get_company_id(symbol: str) -> int:
    """Get company ID from PostgreSQL (cached)"""
    if symbol in _company_id_cache:
        return _company_id_cache[symbol]
    try:
        conn = psycopg2.connect(POSTGRES_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM companies WHERE symbol = %s", (symbol,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        company_id = result[0] if result else None
        if company_id is not None:
            _company_id_cache[symbol] = company_id
        return company_id
    except Exception as e:
        logger.error(f"Error getting company ID: {e}")
        return None

def save_to_postgres(batch_df, epoch_id):
    """Save aggregated sentiment scores to PostgreSQL"""
    try:
        rows = batch_df.collect()
        if not rows:
            return
        conn = psycopg2.connect(POSTGRES_URL)
        cursor = conn.cursor()
        for row in rows:
            company_id = get_company_id(row['company_symbol'])
            if not company_id:
                continue

            cursor.execute("""
                INSERT INTO sentiment_scores 
                (time, company_id, platform, positive_score, negative_score, 
                 neutral_score, overall_sentiment, post_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (time, company_id, platform) DO NOTHING
            """, (
                row['time'],
                company_id,
                row['platform'],
                row['avg_positive'],
                row['avg_negative'],
                row['avg_neutral'],
                row['avg_overall_sentiment'],
                row['post_count']
            ))

        conn.commit()
        cursor.close()
        conn.close()
            
    except Exception as e:
        logger.error(f"Error saving to PostgreSQL: {e}")

def _parse_timestamp(ts):
    """Parse post timestamp from string or datetime."""
    if ts is None:
        return datetime.utcnow()
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except ValueError:
        return datetime.utcnow()

def save_raw_posts_to_postgres(batch_df, epoch_id):
    """Save individual posts to PostgreSQL raw_posts table."""
    try:
        conn = psycopg2.connect(POSTGRES_URL)
        cursor = conn.cursor()
        for spark_row in batch_df.collect():
            row = spark_row.asDict()  # Row has no .get(); dict does
            company_id = get_company_id(row['company_symbol'])
            if not company_id:
                continue
            cursor.execute("""
                INSERT INTO raw_posts
                (post_id, company_id, platform, content, author, timestamp, url, engagement_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_id) DO NOTHING
            """, (
                row['post_id'],
                company_id,
                row['platform'],
                row['content'],
                row.get('author'),
                _parse_timestamp(row['timestamp']),
                row.get('url'),
                row.get('engagement_count', 0) or 0,
            ))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving raw posts to PostgreSQL: {e}")

def save_to_mongodb(batch_df, epoch_id):
    """Save individual posts to MongoDB and PostgreSQL"""
    save_raw_posts_to_postgres(batch_df, epoch_id)
    try:
        from pymongo import MongoClient
        
        sync_client = MongoClient(MONGODB_URL)
        sync_db = sync_client.get_database('sentiment_db')
        sync_collection = sync_db.posts
        
        posts = []
        for spark_row in batch_df.collect():
            row = spark_row.asDict()  # Row has no .get(); dict does
            post = {
                'post_id': row['post_id'],
                'company_symbol': row['company_symbol'],
                'company_name': row['company_name'],
                'platform': row['platform'],
                'content': row['content'],
                'original_content': row.get('original_content') or '',
                'author': row['author'],
                'timestamp': row['timestamp'],
                'url': row.get('url') or '',
                'engagement_count': row.get('engagement_count') or 0,
                'sentiment': {
                    'positive': row['positive'],
                    'negative': row['negative'],
                    'neutral': row['neutral'],
                    'overall': row['overall_sentiment']
                },
                'hashtags': list(row.get('hashtags') or []),
                'mentions': list(row.get('mentions') or []),
                'processed_at': datetime.utcnow().isoformat()
            }
            posts.append(post)
        
        for post in posts:
            try:
                sync_collection.update_one(
                    {'post_id': post['post_id']},
                    {'$set': post},
                    upsert=True,
                )
            except Exception as insert_err:
                logger.debug(f"Mongo upsert skip: {insert_err}")

        sync_client.close()
        
    except Exception as e:
        logger.error(f"Error saving to MongoDB: {e}")

def analyze_sentiment_udf(text):
    """UDF for sentiment analysis"""
    if not text:
        return (0.0, 0.0, 1.0, 0.0)
    
    result = sentiment_analyzer.analyze(text)
    return (
        result['positive'],
        result['negative'],
        result['neutral'],
        result['overall_sentiment']
    )

# Register UDF
sentiment_udf = udf(analyze_sentiment_udf, StructType([
    StructField("positive", DoubleType()),
    StructField("negative", DoubleType()),
    StructField("neutral", DoubleType()),
    StructField("overall_sentiment", DoubleType())
]))

def main():
    """Main streaming pipeline"""
    logger.info("Starting streaming pipeline...")
    
    # Read from Kafka
    raw_stream = spark \
        .readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BROKER) \
        .option("subscribe", "raw_social_data") \
        .option("startingOffsets", "latest") \
        .load()
    
    # Parse JSON
    parsed_stream = raw_stream.select(
        from_json(col("value").cast("string"), raw_schema).alias("data")
    ).select("data.*")
    
    # Filter out null content
    filtered_stream = parsed_stream.filter(col("content").isNotNull())
    
    # Analyze sentiment
    sentiment_stream = filtered_stream.withColumn(
        "sentiment",
        sentiment_udf(col("content"))
    ).select(
        "*",
        col("sentiment.positive").alias("positive"),
        col("sentiment.negative").alias("negative"),
        col("sentiment.neutral").alias("neutral"),
        col("sentiment.overall_sentiment").alias("overall_sentiment")
    )
    
    # Write individual posts to MongoDB
    query1 = sentiment_stream.writeStream \
        .foreachBatch(save_to_mongodb) \
        .outputMode("append") \
        .trigger(processingTime='10 seconds') \
        .start()
    
    # Aggregate by company and platform
    windowed_aggregates = sentiment_stream \
        .withColumn("time", to_timestamp(col("timestamp"))) \
        .withWatermark("time", "1 minute") \
        .groupBy(
            window(col("time"), "1 minute"),
            col("company_symbol"),
            col("platform")
        ).agg(
            avg("positive").alias("avg_positive"),
            avg("negative").alias("avg_negative"),
            avg("neutral").alias("avg_neutral"),
            avg("overall_sentiment").alias("avg_overall_sentiment"),
            count("*").alias("post_count"),
            first("time").alias("time")
        ).select(
            col("time"),
            col("company_symbol"),
            col("platform"),
            col("avg_positive"),
            col("avg_negative"),
            col("avg_neutral"),
            col("avg_overall_sentiment"),
            col("post_count")
        )
    
    # Write aggregates to PostgreSQL
    query2 = windowed_aggregates.writeStream \
        .foreachBatch(save_to_postgres) \
        .outputMode("update") \
        .option("checkpointLocation", "/tmp/checkpoint_scores") \
        .trigger(processingTime='1 minute') \
        .start()
    
    # Also write to Kafka topic for real-time consumption
    query3 = windowed_aggregates \
        .select(
            to_json(struct("*")).alias("value"),
            col("company_symbol").alias("key")
        ).writeStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BROKER) \
        .option("topic", "aggregated_scores") \
        .option("checkpointLocation", "/tmp/checkpoint_aggregated") \
        .trigger(processingTime='1 minute') \
        .start()
    
    logger.info("Streaming queries started. Waiting for termination...")
    
    query3.awaitTermination()

if __name__ == "__main__":
    # Wait for services to be ready
    import time
    time.sleep(10)
    main()

