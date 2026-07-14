"""
Text cleaning utilities for social media posts
"""
import re
import html
from typing import Optional

class TextCleaner:
    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        
        # Decode HTML entities
        text = html.unescape(text)
        
        # Remove URLs
        text = re.sub(r'http\S+|www\.\S+', '', text)
        
        # Remove mentions and hashtags (keep the text)
        text = re.sub(r'@\w+', '', text)
        text = re.sub(r'#(\w+)', r'\1', text)
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters but keep basic punctuation
        text = re.sub(r'[^\w\s.,!?;:()\-\']', '', text)
        
        return text.strip()
    
    @staticmethod
    def extract_hashtags(text: str) -> list:
        """Extract hashtags from text"""
        hashtags = re.findall(r'#(\w+)', text)
        return hashtags
    
    @staticmethod
    def extract_mentions(text: str) -> list:
        """Extract mentions from text"""
        mentions = re.findall(r'@(\w+)', text)
        return mentions
    
    @staticmethod
    def extract_urls(text: str) -> list:
        """Extract URLs from text"""
        urls = re.findall(r'http\S+|www\.\S+', text)
        return urls

