"""
Sentiment analysis using HuggingFace models
"""
import os
import logging
from typing import Dict, List
import numpy as np
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
import torch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SentimentAnalyzer:
    def __init__(self):
        self.models = {}
        self.weights = {
            'twitter-roberta': 0.4,
            'financial-news': 0.4,
            'emotion-detection': 0.2
        }
        self._load_models()
    
    def _load_models(self):
        """Load sentiment models (financial model first for speed/memory)."""
        device = 0 if torch.cuda.is_available() else -1
        try:
            logger.info("Loading FinBERT model...")
            self.models['financial-news'] = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                device=device,
            )
            logger.info("FinBERT loaded successfully")
        except Exception as e:
            logger.error(f"Error loading FinBERT: {e}")

        if not self.models:
            try:
                logger.info("Loading fallback sentiment model...")
                self.models['fallback'] = pipeline(
                    "sentiment-analysis",
                    model="distilbert-base-uncased-finetuned-sst-2-english",
                    device=-1,
                )
            except Exception as e2:
                logger.error(f"Fallback model failed: {e2}")
    
    def _normalize_sentiment(self, label: str, score: float) -> float:
        """Normalize sentiment to -1 to 1 scale"""
        label_lower = label.lower()
        
        if 'positive' in label_lower or 'joy' in label_lower:
            return score
        elif 'negative' in label_lower or 'anger' in label_lower or 'sadness' in label_lower or 'fear' in label_lower:
            return -score
        else:  # neutral
            return 0.0
    
    def _get_emotion_sentiment(self, emotion_label: str, score: float) -> float:
        """Convert emotion to sentiment score"""
        positive_emotions = ['joy', 'surprise']
        negative_emotions = ['anger', 'sadness', 'fear', 'disgust']
        
        if emotion_label.lower() in positive_emotions:
            return score
        elif emotion_label.lower() in negative_emotions:
            return -score
        else:
            return 0.0
    
    def analyze(self, text: str) -> Dict:
        """Analyze sentiment using ensemble of models"""
        if not text or len(text.strip()) < 3:
            return {
                'positive': 0.0,
                'negative': 0.0,
                'neutral': 1.0,
                'overall_sentiment': 0.0
            }
        
        # Truncate text if too long (models have token limits)
        text = text[:512]
        
        results = {}
        weighted_scores = []
        
        try:
            if 'financial-news' in self.models:
                try:
                    result = self.models['financial-news'](text)[0]
                    score = self._normalize_sentiment(result['label'], result['score'])
                    weighted_scores.append(score)
                except Exception as e:
                    logger.warning(f"Financial model error: {e}")

            if 'fallback' in self.models and not weighted_scores:
                try:
                    result = self.models['fallback'](text)[0]
                    score = self._normalize_sentiment(result['label'], result['score'])
                    weighted_scores.append(score)
                except Exception as e:
                    logger.warning(f"Fallback model error: {e}")

            if weighted_scores:
                overall_sentiment = sum(weighted_scores) / len(weighted_scores)
            else:
                overall_sentiment = 0.0
            
            # Convert to positive/negative/neutral distribution
            if overall_sentiment > 0.1:
                positive = min(abs(overall_sentiment), 1.0)
                negative = 0.0
                neutral = 1.0 - positive
            elif overall_sentiment < -0.1:
                positive = 0.0
                negative = min(abs(overall_sentiment), 1.0)
                neutral = 1.0 - negative
            else:
                positive = 0.0
                negative = 0.0
                neutral = 1.0
            
            return {
                'positive': float(positive),
                'negative': float(negative),
                'neutral': float(neutral),
                'overall_sentiment': float(overall_sentiment)
            }
            
        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            return {
                'positive': 0.0,
                'negative': 0.0,
                'neutral': 1.0,
                'overall_sentiment': 0.0
            }

