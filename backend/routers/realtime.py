"""
WebSocket endpoint for real-time updates
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import json
import asyncio
from services.kafka_service import KafkaService

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()
kafka_service = KafkaService()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    try:
        # Send initial connection message
        await websocket.send_json({"status": "connected", "message": "Welcome to IPO Sentiment Analysis"})
        
        # Keep connection alive and handle messages
        while True:
            try:
                # Wait for messages from client (ping/pong)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                await websocket.send_json({"status": "pong", "message": data})
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"status": "heartbeat", "timestamp": str(asyncio.get_event_loop().time())})
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

