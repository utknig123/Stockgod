"""
System Diagnostic Script
Checks connections to PostgreSQL, MongoDB, Kafka, and Redis
"""
import sys
import socket
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, MONGODB_URL, REDIS_URL, KAFKA_BROKER

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'

def print_status(component, status, message=""):
    color = Colors.GREEN if status else Colors.RED
    symbol = "✅" if status else "❌"
    print(f"{symbol} {component:<15} {color}{'CONNECTED' if status else 'FAILED'}{Colors.RESET} {message}")

def check_postgres():
    try:
        import psycopg2
        
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=3
        )
        conn.close()
        print_status("PostgreSQL", True, f"@{POSTGRES_HOST}:{POSTGRES_PORT}")
        return True
    except Exception as e:
        print_status("PostgreSQL", False, str(e))
        return False

def check_mongodb():
    try:
        from pymongo import MongoClient
        
        client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        print_status("MongoDB", True, MONGODB_URL.split('@')[-1])
        return True
    except Exception as e:
        print_status("MongoDB", False, str(e))
        return False

def check_redis():
    try:
        import redis
        
        r = redis.from_url(REDIS_URL, socket_timeout=2)
        r.ping()
        print_status("Redis", True, REDIS_URL)
        return True
    except Exception as e:
        print_status("Redis", False, str(e))
        return False

def check_kafka():
    try:
        import socket
        
        host, port = KAFKA_BROKER.split(':')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, int(port)))
        sock.close()
        
        if result == 0:
            print_status("Kafka Broker", True, KAFKA_BROKER)
            return True
        else:
            print_status("Kafka Broker", False, f"Port {port} closed on {host}")
            return False
    except Exception as e:
        print_status("Kafka Broker", False, str(e))
        return False

def main():
    print(f"\nSystem Check starting at {datetime.now()}\n")
    print("-" * 50)
    
    checks = [
        check_postgres(),
        check_mongodb(),
        check_redis(),
        check_kafka()
    ]
    
    print("-" * 50)
    success_count = sum(1 for c in checks if c)
    print(f"\nSummary: {success_count}/{len(checks)} services healthy")
    
    if success_count < len(checks):
        print("\n\033[93m⚠️  Some services are down. Ensure Docker containers are running:\033[0m")
        print("   docker-compose up -d")

if __name__ == "__main__":
    main()
