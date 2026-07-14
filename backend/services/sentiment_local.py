"""
Lightweight FinBERT sentiment (lazy-loaded) for on-demand analysis.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_analyzer = None
_load_error: Optional[str] = None


def _get_pipeline():
    global _analyzer, _load_error
    if _analyzer is not None:
        return _analyzer
    if _load_error:
        return None
    try:
        from transformers import pipeline
        import torch

        device = 0 if torch.cuda.is_available() else -1
        logger.info("Loading FinBERT for on-demand analysis...")
        _analyzer = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            device=device,
        )
        logger.info("FinBERT ready")
        return _analyzer
    except Exception as e:
        _load_error = str(e)
        logger.error(f"FinBERT load failed: {e}")
        try:
            from transformers import pipeline
            _analyzer = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
                device=-1,
            )
            logger.info("Fallback DistilBERT ready")
            return _analyzer
        except Exception as e2:
            _load_error = str(e2)
            logger.error(f"Fallback model failed: {e2}")
            return None


def _normalize_result(result: dict) -> Dict[str, float]:
    label = (result.get("label") or "").lower()
    score = float(result.get("score") or 0.0)

    if "pos" in label:
        overall = score
    elif "neg" in label:
        overall = -score
    else:
        overall = 0.0

    if overall > 0.1:
        positive, negative, neutral = min(abs(overall), 1.0), 0.0, 1.0 - min(abs(overall), 1.0)
    elif overall < -0.1:
        positive, negative, neutral = 0.0, min(abs(overall), 1.0), 1.0 - min(abs(overall), 1.0)
    else:
        positive, negative, neutral = 0.0, 0.0, 1.0

    return {
        "positive": float(positive),
        "negative": float(negative),
        "neutral": float(neutral),
        "overall_sentiment": float(overall),
    }


def analyze_text(text: str) -> Dict[str, float]:
    """Return positive/negative/neutral/overall_sentiment."""
    if not text or len(text.strip()) < 3:
        return {"positive": 0.0, "negative": 0.0, "neutral": 1.0, "overall_sentiment": 0.0}

    pipe = _get_pipeline()
    text = text[:512]

    if pipe is None:
        return _lexicon_fallback(text)

    try:
        result = pipe(text)[0]
        return _normalize_result(result)
    except Exception as e:
        logger.warning(f"Sentiment inference error: {e}")
        return _lexicon_fallback(text)


def analyze_batch(texts: list, batch_size: int = 24) -> list:
    """Score many texts with FinBERT in batches."""
    if not texts:
        return []
    pipe = _get_pipeline()
    cleaned = [(t or "")[:512] for t in texts]
    if pipe is None:
        return [_lexicon_fallback(t) for t in cleaned]

    results = []
    try:
        for i in range(0, len(cleaned), batch_size):
            chunk = cleaned[i:i + batch_size]
            # Skip empty
            outs = pipe(chunk, truncation=True, max_length=512)
            if isinstance(outs, dict):
                outs = [outs]
            for j, item in enumerate(outs):
                if not chunk[j].strip():
                    results.append({"positive": 0.0, "negative": 0.0, "neutral": 1.0, "overall_sentiment": 0.0})
                else:
                    results.append(_normalize_result(item))
        return results
    except Exception as e:
        logger.warning(f"Batch sentiment failed: {e}; using per-item")
        return [analyze_text(t) for t in cleaned]


def _lexicon_fallback(text: str) -> Dict[str, float]:
    pos_words = {
        "profit", "growth", "surge", "rally", "gain", "beat", "strong", "bullish",
        "upgrade", "record", "rise", "up", "positive", "outperform", "buy", "boom",
        "expansion", "win", "success", "high",
    }
    neg_words = {
        "loss", "fall", "crash", "decline", "weak", "bearish", "downgrade", "miss",
        "cut", "risk", "fraud", "scam", "debt", "lawsuit", "negative", "sell",
        "plunge", "slump", "warning", "low",
    }
    tokens = set(text.lower().replace(".", " ").split())
    pos = len(tokens & pos_words)
    neg = len(tokens & neg_words)
    total = pos + neg
    if total == 0:
        return {"positive": 0.0, "negative": 0.0, "neutral": 1.0, "overall_sentiment": 0.0}
    overall = (pos - neg) / total
    if overall > 0.1:
        return {"positive": abs(overall), "negative": 0.0, "neutral": 1 - abs(overall), "overall_sentiment": overall}
    if overall < -0.1:
        return {"positive": 0.0, "negative": abs(overall), "neutral": 1 - abs(overall), "overall_sentiment": overall}
    return {"positive": 0.0, "negative": 0.0, "neutral": 1.0, "overall_sentiment": 0.0}
