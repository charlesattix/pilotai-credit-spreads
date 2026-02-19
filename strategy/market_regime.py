"""
Market Regime Detection System
Analyzes market conditions and classifies regimes for optimal strategy selection.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import json


class MarketRegimeDetector:
    """Detects and classifies market regimes across multiple dimensions."""
    
    REGIMES = {
        "TRENDING_BULL": {
            "emoji": "🚀",
            "color": "#00ff88",
            "strategies": ["Bull Put Spreads", "Covered Calls", "Cash-Secured Puts"],
            "risk": "Medium",
            "description": "Strong uptrend with momentum"
        },
        "TRENDING_BEAR": {
            "emoji": "🐻",
            "color": "#ff4444",
            "strategies": ["Bear Call Spreads", "Protective Puts", "Short Straddles"],
            "risk": "High",
            "description": "Downtrend with selling pressure"
        },
        "HIGH_VOLATILITY": {
            "emoji": "⚡",
            "color": "#ffaa00",
            "strategies": ["Credit Spreads", "Iron Condors", "Sell Premium"],
            "risk": "Medium-High",
            "description": "Elevated IV - premium selling heaven"
        },
        "LOW_VOLATILITY": {
            "emoji": "😴",
            "color": "#88aaff",
            "strategies": ["Debit Spreads", "Long Options", "Breakout Plays"],
            "risk": "Low",
            "description": "Compressed volatility - cheap options"
        },
        "CHOPPY": {
            "emoji": "🌊",
            "color": "#aa88ff",
            "strategies": ["Range-Bound Trades", "Strangles", "Wait for Clarity"],
            "risk": "Medium",
            "description": "No clear direction - stay nimble"
        },
        "CRASH": {
            "emoji": "💥",
            "color": "#ff0000",
            "strategies": ["Cash", "Protective Puts", "Extreme Caution"],
            "risk": "EXTREME",
            "description": "Market stress - preserve capital"
        },
        "RECOVERY": {
            "emoji": "🌱",
            "color": "#44ff44",
            "strategies": ["Bullish Spreads", "Long Calls", "Accumulation"],
            "risk": "Medium",
            "description": "Bouncing from lows - opportunity"
        }
    }
    
    def __init__(self, tickers: List[str] = None):
        """Initialize with tickers to analyze."""
        self.tickers = tickers or ["SPY", "QQQ", "IWM"]
        self.lookback_days = 60
        
    def analyze(self) -> Dict:
        """Run complete market regime analysis."""
        regimes = {}
        overall_signals = []
        
        for ticker in self.tickers:
            regime_data = self._analyze_ticker(ticker)
            regimes[ticker] = regime_data
            overall_signals.append(regime_data["regime"])
        
        # Determine overall market regime
        overall = self._determine_overall_regime(regimes)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_regime": overall,
            "ticker_regimes": regimes,
            "market_health_score": self._calculate_health_score(regimes),
            "recommendations": self._generate_recommendations(overall, regimes)
        }
    
    def _analyze_ticker(self, ticker: str) -> Dict:
        """Analyze a single ticker for regime classification."""
        try:
            # Fetch data
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.lookback_days)
            
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            
            if data.empty:
                return self._error_regime(ticker)
            
            # Handle multi-level columns
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = ['_'.join(col).strip() if isinstance(col, tuple) else col 
                               for col in data.columns.values]
            
            # Ensure we have clean column names
            close_col = next((col for col in data.columns if 'Close' in col), None)
            high_col = next((col for col in data.columns if 'High' in col), None)
            low_col = next((col for col in data.columns if 'Low' in col), None)
            volume_col = next((col for col in data.columns if 'Volume' in col), None)
            
            if not close_col:
                return self._error_regime(ticker)
            
            close = data[close_col]
            high = data[high_col] if high_col else close
            low = data[low_col] if low_col else close
            volume = data[volume_col] if volume_col else None
            
            # Calculate metrics
            metrics = {
                "trend": self._calculate_trend(close),
                "volatility": self._calculate_volatility(close),
                "momentum": self._calculate_momentum(close),
                "range": self._calculate_range(high, low),
                "volume_trend": self._calculate_volume_trend(volume) if volume is not None else 0
            }
            
            # Classify regime
            regime = self._classify_regime(metrics)
            regime_info = self.REGIMES[regime].copy()
            
            return {
                "ticker": ticker,
                "regime": regime,
                "info": regime_info,
                "metrics": metrics,
                "current_price": float(close.iloc[-1]),
                "price_change_1d": float(((close.iloc[-1] / close.iloc[-2]) - 1) * 100) if len(close) > 1 else 0,
                "price_change_5d": float(((close.iloc[-1] / close.iloc[-6]) - 1) * 100) if len(close) > 5 else 0
            }
            
        except Exception as e:
            print(f"Error analyzing {ticker}: {e}")
            return self._error_regime(ticker)
    
    def _calculate_trend(self, close: pd.Series) -> float:
        """Calculate trend strength (-1 to 1)."""
        if len(close) < 20:
            return 0
        
        # Multiple timeframe moving averages
        ma_5 = close.rolling(5).mean().iloc[-1]
        ma_20 = close.rolling(20).mean().iloc[-1]
        ma_50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else ma_20
        
        current = close.iloc[-1]
        
        # Score based on price vs MAs
        score = 0
        if current > ma_5:
            score += 0.3
        if current > ma_20:
            score += 0.4
        if current > ma_50:
            score += 0.3
        
        # Adjust for MA alignment
        if ma_5 > ma_20 > ma_50:
            score += 0.3  # Strong uptrend
        elif ma_5 < ma_20 < ma_50:
            score -= 0.3  # Strong downtrend
        
        return np.clip(score * 2 - 1, -1, 1)
    
    def _calculate_volatility(self, close: pd.Series) -> float:
        """Calculate volatility level (0 to 1)."""
        if len(close) < 20:
            return 0.5
        
        # 20-day realized volatility
        returns = close.pct_change().dropna()
        volatility = returns.std() * np.sqrt(252)  # Annualized
        
        # Historical context (percentile)
        if len(returns) >= 60:
            rolling_vol = returns.rolling(20).std() * np.sqrt(252)
            percentile = (rolling_vol <= volatility).sum() / len(rolling_vol)
            return float(percentile)
        
        # Normalize: typical SPY vol is 15-20%, spikes to 40-80%
        return np.clip(volatility / 0.4, 0, 1)
    
    def _calculate_momentum(self, close: pd.Series) -> float:
        """Calculate momentum strength (-1 to 1)."""
        if len(close) < 10:
            return 0
        
        # Rate of change over multiple periods
        roc_5 = (close.iloc[-1] / close.iloc[-6] - 1) if len(close) > 5 else 0
        roc_10 = (close.iloc[-1] / close.iloc[-11] - 1) if len(close) > 10 else 0
        
        momentum = (roc_5 * 0.6 + roc_10 * 0.4) * 10  # Scale up
        return float(np.clip(momentum, -1, 1))
    
    def _calculate_range(self, high: pd.Series, low: pd.Series) -> float:
        """Calculate price range compression (0 to 1)."""
        if len(high) < 20:
            return 0.5
        
        # Average true range vs historical
        current_range = (high.iloc[-10:] - low.iloc[-10:]).mean()
        historical_range = (high.iloc[-50:-10] - low.iloc[-50:-10]).mean() if len(high) >= 50 else current_range
        
        if historical_range == 0:
            return 0.5
        
        compression = 1 - (current_range / historical_range)
        return float(np.clip(compression, 0, 1))
    
    def _calculate_volume_trend(self, volume: pd.Series) -> float:
        """Calculate volume trend (-1 to 1)."""
        if volume is None or len(volume) < 20:
            return 0
        
        recent_avg = volume.iloc[-5:].mean()
        historical_avg = volume.iloc[-20:].mean()
        
        if historical_avg == 0:
            return 0
        
        trend = (recent_avg / historical_avg - 1) * 2
        return float(np.clip(trend, -1, 1))
    
    def _classify_regime(self, metrics: Dict) -> str:
        """Classify regime based on metrics."""
        trend = metrics["trend"]
        vol = metrics["volatility"]
        momentum = metrics["momentum"]
        range_val = metrics["range"]
        
        # Crash detection: high vol + strong down momentum
        if vol > 0.7 and momentum < -0.5:
            return "CRASH"
        
        # High volatility regime
        if vol > 0.65:
            return "HIGH_VOLATILITY"
        
        # Low volatility regime
        if vol < 0.3 and range_val > 0.5:
            return "LOW_VOLATILITY"
        
        # Recovery: bouncing from lows
        if trend > 0.3 and momentum > 0.4 and vol > 0.5:
            return "RECOVERY"
        
        # Trending bull
        if trend > 0.4 and momentum > 0.2:
            return "TRENDING_BULL"
        
        # Trending bear
        if trend < -0.4 and momentum < -0.2:
            return "TRENDING_BEAR"
        
        # Default: choppy
        return "CHOPPY"
    
    def _determine_overall_regime(self, regimes: Dict) -> str:
        """Determine overall market regime from ticker regimes."""
        # Weight by importance (SPY > QQQ > IWM)
        weights = {"SPY": 0.5, "QQQ": 0.3, "IWM": 0.2}
        
        regime_scores = {}
        for ticker, data in regimes.items():
            regime = data["regime"]
            weight = weights.get(ticker, 0.1)
            regime_scores[regime] = regime_scores.get(regime, 0) + weight
        
        # Return most weighted regime
        return max(regime_scores.items(), key=lambda x: x[1])[0]
    
    def _calculate_health_score(self, regimes: Dict) -> int:
        """Calculate overall market health score (0-100)."""
        scores = []
        
        for data in regimes.values():
            metrics = data["metrics"]
            
            # Positive factors
            score = 50  # Neutral baseline
            score += metrics["trend"] * 20  # Uptrend is healthy
            score += metrics["momentum"] * 15
            score -= abs(metrics["volatility"] - 0.4) * 30  # Extreme vol is bad
            
            scores.append(np.clip(score, 0, 100))
        
        return int(np.mean(scores))
    
    def _generate_recommendations(self, overall: str, regimes: Dict) -> List[str]:
        """Generate trading recommendations based on regime."""
        regime_info = self.REGIMES[overall]
        recommendations = []
        
        # Regime-specific advice
        recommendations.append(f"{regime_info['emoji']} Market Regime: {overall.replace('_', ' ').title()}")
        recommendations.append(f"📊 {regime_info['description']}")
        recommendations.append(f"⚠️ Risk Level: {regime_info['risk']}")
        recommendations.append("")
        recommendations.append("🎯 Optimal Strategies:")
        
        for i, strategy in enumerate(regime_info["strategies"], 1):
            recommendations.append(f"  {i}. {strategy}")
        
        # Add specific ticker insights
        recommendations.append("")
        recommendations.append("📈 Ticker Analysis:")
        for ticker, data in regimes.items():
            regime_emoji = self.REGIMES[data["regime"]]["emoji"]
            price_change = data["price_change_1d"]
            change_emoji = "📈" if price_change > 0 else "📉"
            recommendations.append(
                f"  {regime_emoji} {ticker}: {data['regime'].replace('_', ' ').title()} "
                f"{change_emoji} {price_change:+.2f}%"
            )
        
        return recommendations
    
    def _error_regime(self, ticker: str) -> Dict:
        """Return error regime data."""
        return {
            "ticker": ticker,
            "regime": "CHOPPY",
            "info": self.REGIMES["CHOPPY"],
            "metrics": {"trend": 0, "volatility": 0.5, "momentum": 0, "range": 0.5, "volume_trend": 0},
            "current_price": 0,
            "price_change_1d": 0,
            "price_change_5d": 0
        }
    
    def format_report(self, analysis: Dict) -> str:
        """Format analysis as a readable report."""
        lines = []
        lines.append("=" * 60)
        lines.append("🎯 MARKET REGIME REPORT")
        lines.append("=" * 60)
        lines.append(f"⏰ Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"💪 Market Health: {analysis['market_health_score']}/100")
        lines.append("")
        
        for rec in analysis["recommendations"]:
            lines.append(rec)
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)


def main():
    """Run market regime analysis."""
    detector = MarketRegimeDetector()
    analysis = detector.analyze()
    
    # Print report
    print(detector.format_report(analysis))
    
    # Save to file
    output_path = "output/market_regime.json"
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2)
    
    print(f"\n💾 Full analysis saved to: {output_path}")


if __name__ == "__main__":
    main()
