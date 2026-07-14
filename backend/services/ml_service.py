"""
ML service for sentiment analysis
"""
import logging
from typing import Dict, List
import numpy as np

logger = logging.getLogger(__name__)

class MLService:
    @staticmethod
    def aggregate_sentiment(scores: List[Dict]) -> Dict:
        """Aggregate sentiment scores"""
        if not scores:
            return {
                'positive': 0.0,
                'negative': 0.0,
                'neutral': 1.0,
                'overall': 0.0
            }
        
        positive = np.mean([s.get('positive_score', 0) for s in scores])
        negative = np.mean([s.get('negative_score', 0) for s in scores])
        neutral = np.mean([s.get('neutral_score', 0) for s in scores])
        overall = np.mean([s.get('overall_sentiment', 0) for s in scores])
        
        return {
            'positive': float(positive),
            'negative': float(negative),
            'neutral': float(neutral),
            'overall': float(overall)
        }
    
    @staticmethod
    def calculate_trend(scores: List[Dict]) -> str:
        """Calculate sentiment trend"""
        if len(scores) < 2:
            return 'stable'
        
        recent = scores[-1].get('overall_sentiment', 0)
        previous = scores[-2].get('overall_sentiment', 0)
        
        diff = recent - previous
        
        if diff > 0.1:
            return 'improving'
        elif diff < -0.1:
            return 'declining'
        else:
            return 'stable'

