"""
Unit tests for ml/combo_regime_detector.py (Phase 6 v2).

Tests verify:
  1. BULL regime — all 3 signals agree bullish
  2. BEAR regime — unanimous (3/3) required
  3. Bear blocked by supermajority — 2 BEAR + 1 BULL → NEUTRAL (not BEAR)
  4. 2023 recovery scenario — MA200=BEAR, RSI=BULL, VIX_struct=BULL → 2/3 BULL → BULL
  5. 2024 brief dip scenario — MA200=BULL, RSI=BEAR, VIX_struct=BEAR → 1B/2B → NEUTRAL
  6. VIX circuit breaker — VIX > 40 → BEAR regardless of other signals
  7. Hysteresis — regime just changed; raw signal wants to flip again → keeps current
  8. MA200 confidence zone — price within 0.5% of MA200 → MA200 abstains
  9. vix_extreme_regime config — VIX spike forces NEUTRAL instead of BEAR when configured
 10. compute_ma200_vote_series — correctly returns bull/bear/neutral per date
"""

import pandas as pd

from ml.combo_regime_detector import ComboRegimeDetector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_data(values: list, start: str = "2020-01-02") -> pd.DataFrame:
    """Build a minimal price DataFrame with a DatetimeIndex and 'Close' column."""
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.DataFrame({"Close": values}, index=idx)


def _make_detector(config: dict = None) -> ComboRegimeDetector:
    base = {
        "signals": ["price_vs_ma200", "rsi_momentum", "vix_structure"],
        "ma_slow_period": 200,
        "ma200_neutral_band_pct": 0.5,
        "rsi_period": 14,
        "rsi_bull_threshold": 55.0,
        "rsi_bear_threshold": 45.0,
        "vix_structure_bull": 0.95,
        "vix_structure_bear": 1.05,
        "bear_requires_unanimous": True,
        "cooldown_days": 10,
        "vix_extreme": 40.0,
    }
    if config:
        base.update(config)
    return ComboRegimeDetector(base)


def _last_regime(detector, price_data, vix_by_date, vix3m_by_date=None):
    """Run compute_regime_series and return the label for the last date."""
    regime = detector.compute_regime_series(price_data, vix_by_date, vix3m_by_date)
    return regime[price_data.index[-1]]


def _make_vix_dict(price_data, vix_val):
    """Constant VIX dict for all dates in price_data."""
    return {ts: float(vix_val) for ts in price_data.index}


def _make_vix3m_dict(price_data, vix3m_val):
    return {ts: float(vix3m_val) for ts in price_data.index}


# ---------------------------------------------------------------------------
# Test 1: BULL — all 3 signals agree bullish
# ---------------------------------------------------------------------------

def test_bull_regime_all_agree():
    """
    price >> MA200, RSI > 55 (rising trend), VIX/VIX3M < 0.95 (contango) → 3 BULL → BULL.
    """
    # 210 days of steadily rising prices: RSI will be high, price >> MA200
    values = [300 + i for i in range(210)]
    df = _make_price_data(values)

    vix     = _make_vix_dict(df, 15.0)   # VIX = 15
    vix3m   = _make_vix3m_dict(df, 18.0) # VIX3M = 18 → ratio = 0.833 < 0.95 → BULL

    detector = _make_detector({"cooldown_days": 0})  # disable hysteresis for unit test
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "BULL", f"Expected BULL, got {label}"


# ---------------------------------------------------------------------------
# Test 2: BEAR — unanimous (3/3) required
# ---------------------------------------------------------------------------

def test_bear_regime_unanimous():
    """
    price << MA200, RSI < 45 (falling trend), VIX/VIX3M > 1.05 (backwardation) → 3 BEAR → BEAR.
    """
    # 210 days of steadily falling prices
    values = [510 - i for i in range(210)]
    df = _make_price_data(values)

    vix     = _make_vix_dict(df, 30.0)   # VIX = 30
    vix3m   = _make_vix3m_dict(df, 25.0) # VIX3M = 25 → ratio = 1.20 > 1.05 → BEAR

    detector = _make_detector({"cooldown_days": 0})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "BEAR", f"Expected BEAR (3/3 unanimous), got {label}"


# ---------------------------------------------------------------------------
# Test 3: Bear blocked by supermajority — 2 BEAR + 1 BULL → NEUTRAL
# ---------------------------------------------------------------------------

def test_bear_blocked_by_supermajority():
    """
    Aug-2024-like scenario:
      MA200: BULL  (price well above 200-day MA anchor)
      RSI:   BEAR  (14 consecutive -1 days push RSI to ~22)
      VIX_structure: BEAR (backwardation: VIX/VIX3M = 1.25)
    → 1 BULL + 2 BEAR → bear_votes=2 < 3 required → NEUTRAL (not BEAR).

    Key data design: 600-day gentle bull (+0.5/day) anchors MA200 far below
    current price.  14-day -1/day dip is small enough (14 pts) that price
    stays ~30 pts above MA200, but large enough to push RSI below 45.
    """
    # 600-day slow bull: price 300 → 599.5, MA200 lags around 450–555
    bull = [300 + i * 0.5 for i in range(600)]
    # 15-day dip: each day drops 1; diff at day 0 = -1 (immediate drop)
    dip  = [598.5 - i for i in range(15)]
    values = bull + dip
    df = _make_price_data(values)

    # VIX below circuit breaker threshold, VIX3M lower → backwardation
    vix   = _make_vix_dict(df, 35.0)   # elevated but not extreme (<40)
    vix3m = _make_vix3m_dict(df, 28.0) # ratio = 35/28 = 1.25 → BEAR signal

    detector = _make_detector({"cooldown_days": 0, "bear_requires_unanimous": True})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "NEUTRAL", (
        f"Expected NEUTRAL (2 BEAR < 3 unanimous required), got {label}. "
        "MA200=BULL + 2 BEAR should NOT reach 3/3 unanimous threshold."
    )


# ---------------------------------------------------------------------------
# Test 4: 2023 recovery scenario — MA200 BEAR, RSI+VIX_struct BULL → BULL
# ---------------------------------------------------------------------------

def test_2023_recovery_scenario():
    """
    Early-2023 analog: price recovering above MA50 (RSI rising) but still below MA200.
      price_vs_ma200: BEAR (price < MA200)
      rsi_momentum:   BULL (RSI recovering > 55)
      vix_structure:  BULL (ratio < 0.95, calm contango)
    → 2 BULL, 1 BEAR → BULL → no bear calls (bear calls correctly blocked in early 2023).
    """
    # 300 days at high plateau (500), then 60 days at depressed (350), then recovering
    plateau = [500.0] * 300
    drop    = [350.0] * 60
    # Recovery: small daily gains → RSI builds up over 14+ days
    recovery = [350.0 + i * 1.5 for i in range(30)]  # 350 → 393.5
    values = plateau + drop + recovery
    df = _make_price_data(values)

    last_price = values[-1]
    ma200_approx = sum(values[-201:-1]) / 200  # mostly 350s and some 500s → ~455
    assert last_price < ma200_approx, (
        f"Setup error: price {last_price:.1f} should be < MA200 {ma200_approx:.1f}"
    )

    # Contango: VIX3M > VIX (calm, market expects recovery)
    vix   = _make_vix_dict(df, 16.0)
    vix3m = _make_vix3m_dict(df, 19.0)  # ratio = 0.842 < 0.95 → BULL

    detector = _make_detector({"cooldown_days": 0})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "BULL", (
        f"2023 recovery: expected BULL (RSI+VIX_struct override MA200 BEAR), got {label}. "
        f"price={last_price:.1f} MA200≈{ma200_approx:.1f}"
    )


# ---------------------------------------------------------------------------
# Test 5: 2024 dip scenario — MA200 BULL, RSI+VIX_struct BEAR → NEUTRAL
# ---------------------------------------------------------------------------

def test_2024_dip_scenario():
    """
    Aug-2024 analog: brief dip in a bull market.
      price_vs_ma200: BULL  (SPY still above MA200 — long-run anchor)
      rsi_momentum:   BEAR  (12 days of -1 drops RSI to ~36)
      vix_structure:  BEAR  (VIX/VIX3M = 1.357 — backwardation)
    → 1 BULL, 2 BEAR → bear_votes=2 < 3 unanimous → NEUTRAL (no bear calls).

    Same core design as test_bear_blocked: long slow bull + small daily dip
    keeps price above MA200 while RSI and VIX structure turn bearish.
    """
    # Same anchor design: 600-day slow bull, then 13-day dip
    bull = [300 + i * 0.5 for i in range(600)]
    dip  = [598.5 - i for i in range(13)]  # 13-day dip (slightly shorter)
    values = bull + dip
    df = _make_price_data(values)

    # VIX spiked into backwardation (below 40 circuit breaker)
    vix   = _make_vix_dict(df, 38.0)   # below 40 threshold
    vix3m = _make_vix3m_dict(df, 28.0) # ratio = 38/28 = 1.357 → BEAR

    detector = _make_detector({"cooldown_days": 0, "bear_requires_unanimous": True})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "NEUTRAL", (
        f"2024 dip: expected NEUTRAL (2 BEAR < 3 unanimous required), got {label}"
    )


# ---------------------------------------------------------------------------
# Test 6: VIX circuit breaker — VIX > 40 → BEAR regardless
# ---------------------------------------------------------------------------

def test_vix_circuit_breaker():
    """
    VIX > 40 triggers circuit breaker → BEAR regardless of other signals.
    Even with rising prices (MA200=BULL, RSI=BULL, VIX_struct=BULL), extreme VIX wins.
    """
    values = [300 + i for i in range(210)]  # rising → all signals BULL
    df = _make_price_data(values)

    # VIX circuit breaker uses PRIOR day's VIX (no lookahead).
    # To fire the CB on the last date, the spike must be on index[-2]
    # so it appears in vix_prev when evaluating the last date.
    vix = {ts: 15.0 for ts in df.index}
    vix[df.index[-2]] = 45.0  # second-to-last day spikes → CB fires on last day

    vix3m = _make_vix3m_dict(df, 18.0)  # ratio would be 45/18 = 2.5 but CB fires first

    detector = _make_detector({"cooldown_days": 0, "vix_extreme": 40.0})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "BEAR", (
        f"VIX circuit breaker: expected BEAR (VIX=45 > 40), got {label}"
    )


# ---------------------------------------------------------------------------
# Test 7: Hysteresis prevents rapid flip
# ---------------------------------------------------------------------------

def test_hysteresis_prevents_flip():
    """
    Regime just changed to BULL. On the very next day, raw signal says NEUTRAL.
    With cooldown_days=10, hysteresis keeps BULL for 10 days.
    """
    # Long falling trend (establishes BEAR), then sharp recovery (signals flip to BULL),
    # then slight dip (RSI dips to neutral — would be NEUTRAL raw signal)
    [500 - i for i in range(210)]   # 500 → 290: establishes BEAR
    # One strong up day that flips RSI+MA200 (simulate by using detector with cooldown)
    # Instead, test hysteresis directly: build a scenario where regime changes then
    # raw signal immediately wants to change back.

    # Design: 210 rising days (→ BULL established), then 1 day where RSI neutral,
    # MA200 just barely in band (abstains), VIX neutral → raw=NEUTRAL.
    # With cooldown=10, should stay BULL.
    [300 + i for i in range(210)]
    # Last bar: price dropped back near MA200 (in neutral band), RSI neutral
    # We'll set MA200 ≈ current price, RSI ≈ 50 (neutral), VIX_struct neutral
    # The simplest approach: just check that after a recent change, the regime holds.
    # Use a two-phase dataset: phase1 all BULL signals, phase2 all ambiguous.

    # Phase 1: 220 days all-BULL (price rising fast, RSI > 55, VIX contango)
    phase1 = [300 + i * 2 for i in range(220)]
    # Phase 2: 5 days where raw signal would be NEUTRAL (RSI dips to 50, VIX neutral band)
    phase2_start = phase1[-1]
    phase2 = [phase2_start - i * 0.1 for i in range(5)]  # tiny dip (stays above MA200)
    values = phase1 + phase2
    df = _make_price_data(values)

    # VIX in neutral band for last 5 days (0.95–1.05 → abstain)
    vix   = {ts: 15.0 for ts in df.index}
    vix3m = {ts: 18.0 for ts in df.index}
    for ts in df.index[-5:]:
        vix[ts]   = 20.0   # ratio = 20/20 = 1.0 → neutral band → abstain
        vix3m[ts] = 20.0

    detector = _make_detector({"cooldown_days": 10})
    regime_series = detector.compute_regime_series(df, vix, vix3m)

    # The last 5 days should still be BULL due to hysteresis (regime change < 10 days ago)
    last_labels = [regime_series[ts] for ts in df.index[-5:]]
    assert all(lbl == "BULL" for lbl in last_labels), (
        f"Hysteresis: expected BULL to persist, got {last_labels}"
    )


# ---------------------------------------------------------------------------
# Test 8: MA200 confidence zone — price within 0.5% of MA200 → abstains
# ---------------------------------------------------------------------------

def test_ma200_confidence_zone():
    """
    Price is within 0.5% of MA200 → MA200 signal abstains.
    RSI neutral (45–55 band) → abstains.
    VIX_struct neutral (0.95–1.05) → abstains.
    → 0 BULL, 0 BEAR → NEUTRAL.
    """
    # 210 days flat at 400 → MA200 ≈ 400, price ≈ 400 (within band)
    values = [400.0] * 210
    df = _make_price_data(values)

    # All signals in neutral/abstain zone
    vix   = _make_vix_dict(df, 20.0)   # ratio = 20/20 = 1.0 → neutral band
    vix3m = _make_vix3m_dict(df, 20.0)

    detector = _make_detector({"cooldown_days": 0})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "NEUTRAL", (
        f"MA200 confidence zone: all signals abstaining, expected NEUTRAL, got {label}"
    )


# ---------------------------------------------------------------------------
# Test 9: vix_extreme_regime='NEUTRAL' — VIX spike forces NEUTRAL not BEAR
# ---------------------------------------------------------------------------

def test_vix_extreme_regime_neutral():
    """
    vix_extreme_regime='NEUTRAL': when VIX circuit breaker fires the regime
    should be NEUTRAL instead of the default BEAR.  All other signals are
    bullish — this isolates the CB path.
    """
    values = [300 + i for i in range(210)]  # rising → all signals BULL
    df = _make_price_data(values)

    # Spike VIX on second-to-last day so CB fires on the last date (prev-day logic)
    vix = {ts: 15.0 for ts in df.index}
    vix[df.index[-2]] = 45.0

    vix3m = _make_vix3m_dict(df, 18.0)

    detector = _make_detector({"cooldown_days": 0, "vix_extreme": 40.0, "vix_extreme_regime": "NEUTRAL"})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "NEUTRAL", (
        f"vix_extreme_regime=NEUTRAL: VIX CB should force NEUTRAL, got {label}"
    )


def test_vix_extreme_regime_default_is_bear():
    """
    Default vix_extreme_regime is 'BEAR' — backward-compatible with existing tests.
    """
    values = [300 + i for i in range(210)]
    df = _make_price_data(values)

    vix = {ts: 15.0 for ts in df.index}
    vix[df.index[-2]] = 45.0
    vix3m = _make_vix3m_dict(df, 18.0)

    detector = _make_detector({"cooldown_days": 0, "vix_extreme": 40.0})
    label = _last_regime(detector, df, vix, vix3m)
    assert label == "BEAR", (
        f"Default vix_extreme_regime: expected BEAR, got {label}"
    )


# ---------------------------------------------------------------------------
# Test 10: compute_ma200_vote_series — bull / bear / neutral votes
# ---------------------------------------------------------------------------

def test_compute_ma200_vote_series_bull():
    """Price well above MA200 → vote series ends with 'bull'."""
    values = [300 + i for i in range(210)]  # steadily rising
    df = _make_price_data(values)
    detector = _make_detector()
    votes = detector.compute_ma200_vote_series(df)
    last_vote = votes[df.index[-1]]
    assert last_vote == "bull", f"Expected 'bull', got '{last_vote}'"


def test_compute_ma200_vote_series_bear():
    """Price well below MA200 → vote series ends with 'bear'."""
    # 300 days descending: price drops far below where MA200 anchors
    values = [600 - i for i in range(210)]
    df = _make_price_data(values)
    detector = _make_detector()
    votes = detector.compute_ma200_vote_series(df)
    last_vote = votes[df.index[-1]]
    assert last_vote == "bear", f"Expected 'bear', got '{last_vote}'"


def test_compute_ma200_vote_series_neutral_band():
    """Price flat at MA200 (within band) → vote is 'neutral'."""
    values = [400.0] * 210
    df = _make_price_data(values)
    detector = _make_detector()
    votes = detector.compute_ma200_vote_series(df)
    last_vote = votes[df.index[-1]]
    assert last_vote == "neutral", f"Expected 'neutral' (within band), got '{last_vote}'"
