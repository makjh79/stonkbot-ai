"""
STONK.AI Risk Engine v2.1

Position sizing, concentration limits, drawdown circuit breakers,
and cash guardrails.  The risk engine is intentionally conservative:
its job is to keep the bot alive long enough for the signal edge to work.

v2.1 changes:
- Dynamic cash floor that scales with portfolio drawdown
- Entry cash buffer (target 7% cash on new buys, not 5%)
- check_cash_raise(): proactively trim weakest positions when cash < floor
"""

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from alpaca_data import get_data_hub

logger = logging.getLogger(__name__)

def load_high_beta_symbols(
    report_path: str = "/var/www/hedge-fund-website/correlation_report.json",
    beta_threshold: float = 1.2,
    corr_threshold: float = 0.70,
) -> Set[str]:
    """Load the high-beta basket from the correlation report.

    Falls back to empty set if the report is missing or malformed.
    Thresholds are defaults; callers may override.
    """
    try:
        data = json.loads(Path(report_path).read_text())
        basket = set()
        for symbol, metrics in data.get("betas", {}).items():
            beta = metrics.get("spy")
            corr = metrics.get("spy_corr")
            if (beta is not None and beta > beta_threshold) or (corr is not None and corr > corr_threshold):
                basket.add(symbol)
        return basket
    except Exception as e:
        logger.debug(f"Could not load high-beta symbols from {report_path}: {e}")
        return set()


def is_stop_reason(reason: str) -> bool:
    """True if a sell rationale is a stop-loss (vs profit take/trim/rotation).
    Used to decide which sells trigger the re-entry cooldown."""
    r = (reason or "").lower()
    return any(k in r for k in (
        "hard cut", "hard stop", "hard_stop", "trailing stop", "vwap stop",
        "stop loss", "stop:",
    ))


@dataclass
class RiskConfig:
    # --- Market hours / extended hours ---
    extended_hours_enabled: bool = False          # default: do not trade extended hours

    # --- Cash & deployment guardrails ---
    allow_margin: bool = False                    # never use margin; cash-only orders
    min_cash_absolute: float = 2000.0            # hard floor, regardless of portfolio size
    min_cash_pct: float = 0.10                  # hold at least 10% cash (aligned with RISK_ON regime)
    entry_cash_buffer_pct: float = 0.12           # leave 12% cash after new buys (buffer above 10% floor)
    slippage_buffer: float = 0.98               # assume 2% worse fill

    # --- Dynamic cash floor (scales with drawdown) ---
    # At high water mark: min_cash_pct (10%). As drawdown deepens, floor rises.
    dynamic_cash_floor: Dict[float, float] = None  # set in __post_init__
    # Format: {drawdown_threshold: floor_pct}
    # e.g. {0.05: 0.06, 0.10: 0.08, 0.15: 0.10} means:
    #   at 5%+ drawdown → 6% floor, at 10%+ → 8% floor, at 15%+ → 10% floor

    # --- Cash-raising logic ---
    cash_raise_enabled: bool = True              # proactively trim to raise cash when below floor
    cash_raise_min_position_value: float = 500.0  # don't trim positions worth less than this
    cash_raise_max_trims_per_cycle: int = 2       # max positions to trim per scan cycle
    cash_raise_readiness_threshold: float = 50.0  # only trim positions with readiness below this

    # --- Rotation logic: rebalance from weak to strong ---
    rotation_enabled: bool = True              # trim overweight low-readiness to fund high-readiness entries
    rotation_min_position_pct: float = 0.05    # only trim positions > 5% of portfolio
    rotation_max_trims_per_cycle: int = 2       # max positions to rotate per cycle
    rotation_readiness_gap: float = 15.0        # min readiness gap between trim target and buy target
    rotation_min_trim_pct: float = 0.15         # trim at least 15% of position when rotating
    rotation_cooldown_hours: float = 2.0       # only rotate once per cooldown period

    # --- Averaging in controls ---
    avg_in_cooldown_hours: float = 24.0            # minimum hours between adds to same position
    avg_in_risk_multiplier: float = 0.5            # half the vol risk of a new position

    # --- Dip-buy deployment ladder ---
    dip_position_multiplier: Dict[float, float] = None  # set in __post_init__

    def __post_init__(self):
        if self.dip_position_multiplier is None:
            self.dip_position_multiplier = {
                0.00: 1.00,   # normal times
                0.05: 1.25,   # -5% drawdown
                0.10: 1.50,   # -10% drawdown
                0.15: 2.00,   # -15% drawdown
                0.20: 3.00,   # -20%+ drawdown
            }
        if self.dynamic_cash_floor is None:
            self.dynamic_cash_floor = {
                0.00: 0.10,   # at high: 10% floor (aligned with RISK_ON regime)
                0.05: 0.12,   # -5% drawdown: 12% floor
                0.10: 0.15,   # -10% drawdown: 15% floor
                0.15: 0.20,   # -15% drawdown: 20% floor
                0.20: 0.25,   # -20%+ drawdown: 25% floor
            }

    # --- Concentration ---
    max_single_position_pct: float = 0.10          # loosened from 8% to improve capital deployment while maintaining concentration guard
    max_sector_pct: float = 0.25                   # loosened from 20% to allow better deployment across clustered Fintech/Consumer signals
    concentration_trim_trigger: float = 1.00      # trim at cap, not 25% above (was 1.25)

    # --- Anti-churn guardrails (2026-07-18) ---
    concentration_trim_band: float = 0.005        # only trim when position exceeds cap by this much (0.5pp) — prevents 1-share dust trims
    concentration_trim_target_buffer: float = 0.01  # trim down to 1pp BELOW cap so small price moves don't re-trigger
    min_trim_notional: float = 250.0              # never place a trim smaller than $250
    trim_cooldown_hours: float = 4.0              # per-symbol cooldown between concentration/sector trims
    stop_reentry_cooldown_hours: float = 20.0     # after any stop-loss sell, block re-entry for ~1 trading day
    max_entries_per_symbol_per_day: int = 1       # machine-gun guard: max 1 NEW entry per symbol per day

    # --- High-beta basket (macro correlation guard) ---
    high_beta_basket_cap_enabled: bool = True
    max_high_beta_deployed_pct: float = 0.35        # cap deployed capital in high-beta basket
    high_beta_spy_beta_threshold: float = 1.2       # SPY beta threshold
    high_beta_spy_corr_threshold: float = 0.70      # SPY correlation threshold

    # --- Loss / drawdown controls ---
    new_entry_max_drawdown_pct: float = -0.10     # halt new buys at -10% DD (tightened from -15%) 
    hard_stop_loss_pct: float = -0.10               # sell any position down 10%
    trailing_stop_pct: float = -0.10               # base: sell if position falls 10% from its peak
    trailing_stop_atr_multiplier: float = 2.0       # ATR multiple for trailing stop
    hard_stop_atr_multiplier: float = 1.5           # ATR multiple for hard stop (replaces fixed 10%)
    max_hard_stop_pct: float = -0.08                # never wider than 8% even for low-vol stocks
    min_hard_stop_pct: float = -0.03                # never tighter than 3% (avoid noise kills)
    trim_profit_pct: float = 0.25                  # trim 1/3 at +25%
    full_exit_profit_pct: float = 0.50             # full exit at +50%

    # --- Sizing ---
    target_position_risk: float = 0.015             # each new position targets 1.5% portfolio vol risk
    min_trade_notional: float = 500.0               # skip trades below $500

    # --- Universe / gate ---
    top_signal_count: int = 20                      # consider top 20 signals (watchlist size); bot holds max 10

    # --- VWAP stops (new with Alpaca paid data) ---
    vwap_stop_enabled: bool = True                 # use intraday VWAP as stop reference
    vwap_stop_buffer_pct: float = -0.02            # sell if 2% below VWAP
    vwap_trailing_enabled: bool = True              # use VWAP as dynamic trailing stop
    vwap_trailing_atr_multiplier: float = 2.0      # ATR multiple below VWAP for trailing


@dataclass
class SizingResult:
    symbol: str
    qty: int
    intended_notional: float
    reason: str
    blocked: bool = False
    block_reason: str = ""


class RiskEngine:
    def __init__(self, config: Optional[RiskConfig] = None,
                 state_file: Optional[Path] = None,
                 initial_portfolio_value: float = 100_000.0,
                 paper_mode: bool = False):
        self.config = config or RiskConfig()
        if paper_mode and self.config.max_sector_pct <= 0.25:
            self.config.max_sector_pct = 0.30  # paper-only looser sector cap
        self.state_file = state_file or Path("risk_state.json")
        self.initial_portfolio_value = initial_portfolio_value
        self.high_water_mark = initial_portfolio_value
        self.daily_buys_deployed: Dict[str, float] = {}
        self.cash_at_open: Dict[str, float] = {}
        self.last_state_date: Optional[str] = None
        self.position_high_water_marks: Dict[str, float] = {}
        self.position_atr_pct: Dict[str, float] = {}
        self.position_last_add_time: Dict[str, str] = {}
        self.position_last_trim_time: Dict[str, str] = {}   # anti-churn: per-symbol trim cooldown
        self.stopped_out: Dict[str, str] = {}               # symbol -> ISO timestamp of last stop-loss sell
        self.entries_today: Dict[str, str] = {}             # symbol -> ISO date of last NEW entry (1/day cap)
        self.last_rotation_time: Optional[datetime] = None
        self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file) as f:
                data = json.load(f)
            self.high_water_mark = data.get("high_water_mark", self.high_water_mark)
            self.daily_buys_deployed = data.get("daily_buys_deployed", {})
            self.cash_at_open = data.get("cash_at_open", {})
            self.last_state_date = data.get("last_state_date")
            self.position_high_water_marks = data.get("position_high_water_marks", {})
            self.position_atr_pct = data.get("position_atr_pct", {})
            self.position_last_add_time = data.get("position_last_add_time", {})
            self.position_last_trim_time = data.get("position_last_trim_time", {})
            self.stopped_out = data.get("stopped_out", {})
            self.entries_today = data.get("entries_today", {})
        except Exception as e:
            logger.warning(f"Could not load risk state: {e}")

    def _save_state(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump({
                    "high_water_mark": self.high_water_mark,
                    "daily_buys_deployed": self.daily_buys_deployed,
                    "cash_at_open": self.cash_at_open,
                    "last_state_date": self.last_state_date,
                    "position_high_water_marks": self.position_high_water_marks,
                    "position_atr_pct": self.position_atr_pct,
                    "position_last_add_time": self.position_last_add_time,
                    "position_last_trim_time": self.position_last_trim_time,
                    "stopped_out": self.stopped_out,
                    "entries_today": self.entries_today,
                    "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save risk state: {e}")

    def _today(self) -> str:
        return date.today().isoformat()

    def _reset_daily(self, portfolio_value: float, cash: float):
        today = self._today()
        if self.last_state_date != today:
            self.daily_buys_deployed[today] = 0.0
            self.cash_at_open[today] = cash
            self.last_state_date = today
            logger.info(f"New day: cash_at_open=${cash:,.2f}, daily buy budget reset")

    def record_buy(self, notional: float):
        today = self._today()
        self.daily_buys_deployed[today] = self.daily_buys_deployed.get(today, 0.0) + notional
        self._save_state()

    # ------------------------------------------------------------------
    # Anti-churn guardrails (2026-07-18)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_ts(ts: str) -> Optional[datetime]:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def record_stop_out(self, symbol: str, reason: str = ""):
        """Record a stop-loss sell; blocks re-entry for stop_reentry_cooldown_hours."""
        self.stopped_out[symbol] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        logger.info(f"STOP-OUT recorded: {symbol} — re-entry blocked for {self.config.stop_reentry_cooldown_hours:.0f}h ({reason})")
        self._save_state()

    def in_stop_cooldown(self, symbol: str) -> bool:
        """True if symbol was stopped out within the cooldown window."""
        ts = self.stopped_out.get(symbol)
        if not ts:
            return False
        dt = self._parse_ts(ts)
        if dt is None:
            self.stopped_out.pop(symbol, None)
            return False
        elapsed_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if elapsed_h >= self.config.stop_reentry_cooldown_hours:
            # Cooldown expired — clean up lazily
            self.stopped_out.pop(symbol, None)
            return False
        return True

    def reset_position_tracking(self, symbol: str):
        """Clear high-water mark and ATR tracking when a position is fully exited.

        Prevents the whipsaw bug where a re-entered symbol inherits a stale peak
        from a previous holding period and instantly triggers its trailing stop
        (root cause of the 2026-07-16 LCID 30x stop/re-entry loop and the bogus
        $775.98 CRWD peak).
        """
        removed = self.position_high_water_marks.pop(symbol, None)
        self.position_atr_pct.pop(symbol, None)
        if removed is not None:
            logger.info(f"Peak reset: {symbol} high-water mark ${removed:.2f} cleared on full exit")
            self._save_state()

    def record_entry(self, symbol: str):
        """Record a NEW position entry (not avg-in) for the 1-per-day entry cap."""
        self.entries_today[symbol] = self._today()
        self._save_state()

    def entries_today_count(self, symbol: str) -> int:
        """1 if a NEW entry already happened for this symbol today, else 0."""
        d = self.entries_today.get(symbol)
        if d is None:
            return 0
        if d != self._today():
            self.entries_today.pop(symbol, None)
            return 0
        return 1

    def _trim_on_cooldown(self, symbol: str) -> bool:
        ts = self.position_last_trim_time.get(symbol)
        if not ts:
            return False
        dt = self._parse_ts(ts)
        if dt is None:
            self.position_last_trim_time.pop(symbol, None)
            return False
        elapsed_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if elapsed_h >= self.config.trim_cooldown_hours:
            self.position_last_trim_time.pop(symbol, None)
            return False
        return True

    def _record_trim(self, symbol: str):
        self.position_last_trim_time[symbol] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def anomalous_positions(self, portfolio_data: Dict) -> List[Dict]:
        """Detect short/negative positions the long-only strategy cannot manage
        (e.g. the 2026-07-16 accidental GTLB short from an external manual sell).
        Returns list of offending positions; caller should alert, never auto-trade."""
        bad = []
        for pos in portfolio_data.get("positions", []):
            qty = pos.get("qty", 0)
            mv = pos.get("market_value", 0)
            if qty < 0 or mv < 0:
                bad.append({
                    "symbol": pos.get("symbol"),
                    "qty": qty,
                    "market_value": mv,
                    "unrealized_plpc": pos.get("unrealized_plpc", 0),
                })
        return bad

    def record_high_water(self, portfolio_value: float):
        if portfolio_value > self.high_water_mark:
            self.high_water_mark = portfolio_value
            self._save_state()

    # ------------------------------------------------------------------
    # Dynamic cash floor
    # ------------------------------------------------------------------

    def _current_drawdown(self, portfolio_value: float) -> float:
        self.record_high_water(portfolio_value)
        return max(0.0, (self.high_water_mark - portfolio_value) / self.high_water_mark)

    def _effective_cash_floor_pct(self, drawdown: float) -> float:
        """Return the cash floor percentage scaled by current drawdown."""
        ladder = self.config.dynamic_cash_floor
        active_pct = self.config.min_cash_pct
        for threshold in sorted(ladder.keys()):
            if drawdown >= threshold:
                active_pct = ladder[threshold]
        return active_pct

    def _cash_floor(self, portfolio_value: float) -> float:
        """Compute the current cash floor ($), dynamically scaled by drawdown."""
        drawdown = self._current_drawdown(portfolio_value)
        floor_pct = self._effective_cash_floor_pct(drawdown)
        floor = max(floor_pct * portfolio_value, self.config.min_cash_absolute)
        return floor

    def _entry_cash_buffer(self, portfolio_value: float) -> float:
        """Cash buffer to leave after new buys (higher than floor to prevent
        immediately dipping below floor on the next scan)."""
        # Use entry_cash_buffer_pct, but still at least min_cash_absolute
        return max(self.config.entry_cash_buffer_pct * portfolio_value, self.config.min_cash_absolute)

    def _dip_position_multiplier(self, drawdown: float) -> float:
        """Return position-size multiplier based on portfolio drawdown."""
        ladder = self.config.dip_position_multiplier
        active_threshold = 0.0
        for threshold in sorted(ladder.keys()):
            if drawdown >= threshold:
                active_threshold = threshold
        return ladder.get(active_threshold, 1.0)

    def can_add_new_positions(self, portfolio_data: Dict) -> Tuple[bool, str, float]:
        """Return (allowed, reason, reserve_cash_deployable)."""
        pv = portfolio_data.get("account", {}).get("portfolio_value", 0)
        cash = portfolio_data.get("account", {}).get("cash", 0)

        if pv <= 0:
            return False, "invalid portfolio value", 0.0

        drawdown = self._current_drawdown(pv)
        if drawdown >= abs(self.config.new_entry_max_drawdown_pct):
            return False, f"drawdown {drawdown:.1%} exceeds limit {abs(self.config.new_entry_max_drawdown_pct):.1%}", 0.0

        # Dynamic cash floor
        cash_floor = self._cash_floor(pv)
        reserve_cash = max(0.0, cash - cash_floor)

        if reserve_cash <= 0:
            return False, f"cash ${cash:,.2f} at or below floor ${cash_floor:,.2f} (floor {self._effective_cash_floor_pct(drawdown):.1%} at {drawdown:.1%} drawdown)", 0.0

        return True, "ok", reserve_cash

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def size_average_in(
        self,
        symbol: str,
        price: float,
        atr: float,
        portfolio_data: Dict,
        current_positions: Dict[str, Dict],
        signal_score: float = 0.0,
        max_position_pct_override: float = 0.0,
    ) -> SizingResult:
        """Compute a smaller add qty for an existing position."""
        pv = portfolio_data.get("account", {}).get("portfolio_value", 0)
        cash = portfolio_data.get("account", {}).get("cash", 0)

        if price <= 0 or pv <= 0:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason="invalid price or portfolio value")

        can_add, reason, _ = self.can_add_new_positions(portfolio_data)
        if not can_add:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=reason)

        # Cooldown check
        last_add = self.position_last_add_time.get(symbol)
        if last_add:
            try:
                last = datetime.fromisoformat(last_add.replace("Z", "+00:00"))
                hours_since = (datetime.now(timezone.utc) - last).total_seconds() / 3600
                if hours_since < self.config.avg_in_cooldown_hours:
                    return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=f"avg-in cooldown: {hours_since:.1f}h since last add")
            except Exception:
                pass

        effective_max_pct = max_position_pct_override if max_position_pct_override > 0 else self.config.max_single_position_pct
        existing_mv = current_positions.get(symbol, {}).get("market_value", 0)
        current_pct = existing_mv / pv
        if current_pct >= effective_max_pct:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=f"position already {current_pct:.1%}")

        headroom_pct = effective_max_pct - current_pct
        if headroom_pct <= 0:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason="position at cap")

        atr_pct = atr / price if atr > 0 and price > 0 else 0.02
        if atr_pct > 0:
            risk_target = pv * self.config.target_position_risk * self.config.avg_in_risk_multiplier
            risk_based_notional = risk_target / atr_pct
        else:
            risk_based_notional = pv * (self.config.max_single_position_pct / 4)

        # Use entry cash buffer (7%) instead of floor (5%) for new buys
        cash_buffer = self._entry_cash_buffer(pv)
        max_add_by_headroom = pv * headroom_pct
        target_notional = min(
            max_add_by_headroom,
            risk_based_notional,
            max(0.0, cash - cash_buffer),
        )

        usable_notional = target_notional * self.config.slippage_buffer
        if usable_notional < self.config.min_trade_notional:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=f"avg-in notional ${usable_notional:,.2f} too small")

        qty = max(1, int(usable_notional / price))
        cost = qty * price
        if cost > cash - cash_buffer:
            qty = max(0, int((cash - cash_buffer) / price))
            cost = qty * price

        if qty < 1 or cost < self.config.min_trade_notional:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason="insufficient cash for avg-in (buffer)")

        return SizingResult(
            symbol=symbol,
            qty=qty,
            intended_notional=cost,
            reason=(
                f"avg-in score={signal_score:.1f} atr%={atr_pct:.2%} "
                f"target=${target_notional:,.0f} qty={qty}"
            ),
        )

    def record_average_in(self, symbol: str, notional: float):
        """Record an averaging-in purchase for cooldown tracking."""
        self.position_last_add_time[symbol] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.record_buy(notional)

    def size_buy(
        self,
        symbol: str,
        price: float,
        atr: float,
        portfolio_data: Dict,
        current_positions: Optional[Dict[str, Dict]] = None,
        signal_score: float = 0.0,
        max_position_pct_override: float = 0.0,
    ) -> SizingResult:
        """Compute a buy qty for a single candidate, or return a blocked result."""
        if current_positions is None:
            current_positions = {}

        pv = portfolio_data.get("account", {}).get("portfolio_value", 0)
        cash = portfolio_data.get("account", {}).get("cash", 0)

        # Basic sanity
        if price <= 0 or pv <= 0:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason="invalid price or portfolio value")

        can_add, reason, deployable_reserve = self.can_add_new_positions(portfolio_data)
        if not can_add:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=reason)

        self._reset_daily(pv, cash)

        # Position cap check — use tier override if provided
        effective_max_pct = max_position_pct_override if max_position_pct_override > 0 else self.config.max_single_position_pct
        existing_mv = current_positions.get(symbol, {}).get("market_value", 0)
        current_pct = existing_mv / pv
        if current_pct >= effective_max_pct:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=f"position already {current_pct:.1%}")

        # Sector cap check
        sector = current_positions.get(symbol, {}).get("sector", "Other")
        sector_mv = sum(p.get("market_value", 0) for p in current_positions.values()
                        if p.get("sector", "Other") == sector)
        sector_pct = sector_mv / pv
        if sector_pct >= self.config.max_sector_pct:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=f"sector {sector} already {sector_pct:.1%}")

        # Risk-parity-ish sizing: target vol risk / (ATR% of price)
        atr_pct = 0.0
        if atr > 0 and price > 0:
            atr_pct = atr / price
            risk_target = pv * self.config.target_position_risk
            risk_based_notional = risk_target / atr_pct
        else:
            risk_based_notional = pv * (self.config.max_single_position_pct / 2)

        # Record ATR% for this symbol so trailing stop can be volatility-aware
        if atr_pct > 0:
            self.position_atr_pct[symbol] = atr_pct
            self._save_state()

        # Apply dip-buy sizing multiplier based on portfolio drawdown
        drawdown = self._current_drawdown(pv)
        dip_multiplier = self._dip_position_multiplier(drawdown)
        risk_based_notional *= dip_multiplier

        # Use entry cash buffer (7%) instead of floor (5%) — builds a buffer
        cash_buffer = self._entry_cash_buffer(pv)

        # Target position value cap — use tier override if provided
        target_notional = min(
            pv * effective_max_pct,                            # tier-adjusted cap (8% NOW, 12% STRONG_NOW)
            risk_based_notional,                             # volatility-adjusted with dip multiplier
            max(0.0, cash - cash_buffer),                     # available cash after buffer
        )

        # Slippage buffer
        usable_notional = target_notional * self.config.slippage_buffer
        if usable_notional < self.config.min_trade_notional:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason=f"usable notional ${usable_notional:,.2f} too small")

        qty = max(1, int(usable_notional / price))
        cost = qty * price
        if cost > cash - cash_buffer:
            qty = max(0, int((cash - cash_buffer) / price))
            cost = qty * price

        if qty < 1 or cost < self.config.min_trade_notional:
            return SizingResult(symbol, 0, 0.0, "", blocked=True, block_reason="insufficient cash after buffer")

        return SizingResult(
            symbol=symbol,
            qty=qty,
            intended_notional=cost,
            reason=(
                f"score={signal_score:.1f} atr%={atr/price:.2%} "
                f"target=${target_notional:,.0f} qty={qty}"
            ),
        )

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def check_exits(self, portfolio_data: Dict) -> List[Dict]:
        trades = []

        # Prune peak/ATR tracking for symbols no longer held (qty > 0 = held).
        # Without this, a re-entered symbol inherits a stale peak from a previous
        # holding period and its trailing stop fires instantly (LCID/CRWD whipsaw).
        held = {p.get("symbol") for p in portfolio_data.get("positions", []) if p.get("qty", 0) > 0}
        for sym in list(self.position_high_water_marks.keys()):
            if sym not in held:
                self.position_high_water_marks.pop(sym, None)
                self.position_atr_pct.pop(sym, None)

        # Update per-position high water marks and ATR% from current prices
        for pos in portfolio_data.get("positions", []):
            symbol = pos.get("symbol")
            if pos.get("qty", 0) <= 0:
                continue  # short/anomalous — long-only logic does not apply
            current = pos.get("current", 0)
            if current > 0:
                prev_peak = self.position_high_water_marks.get(symbol, current)
                self.position_high_water_marks[symbol] = max(prev_peak, current)
            # Update ATR% if provided in position data
            atr = pos.get("atr")
            if atr and current > 0:
                self.position_atr_pct[symbol] = atr / current
        self._save_state()

        for pos in portfolio_data.get("positions", []):
            symbol = pos.get("symbol")
            qty = pos.get("qty", 0)
            if qty <= 0:
                continue  # short/anomalous position — alert handled in run_cycle, never trade it here
            current = pos.get("current", 0)
            plpc = pos.get("unrealized_plpc", 0) / 100  # stored as percent in portfolio_data
            avg_entry = pos.get("avg_entry", 0) or 0
            peak = self.position_high_water_marks.get(symbol, current)
            # Garbage-peak clamp: full profit exit fires at +50%, so a legit peak
            # can never exceed ~1.5x the greater of entry/current. Anything beyond
            # is corrupt data (e.g. CRWD peak $775.98 with price ~$205).
            _peak_cap = max(avg_entry, current) * 1.5 if max(avg_entry, current) > 0 else peak
            if peak > _peak_cap:
                logger.warning(f"PEAK CLAMP: {symbol} peak ${peak:.2f} exceeds 1.5x entry/current — clamped to ${_peak_cap:.2f}")
                peak = _peak_cap
                self.position_high_water_marks[symbol] = peak

            # 0. Absolute hard cut: any position down -5% exits immediately
            if plpc <= -0.05:
                reason = f"Hard cut: {plpc:.1%} (absolute -5% limit)"
                trades.append({
                    "symbol": symbol,
                    "qty": qty,
                    "action": "SELL",
                    "reason": reason,
                })
                logger.warning(f"HARD CUT: {symbol} at {plpc:.1%} — immediate exit due to >5% loss")
                self.record_stop_out(symbol, reason)
                continue

            # 1. Hard stop loss — ATR-based (1.5x ATR), clamped to [3%, 8%]
            atr_pct = self.position_atr_pct.get(symbol, 0)
            if atr_pct > 0:
                atr_hard_stop = -(atr_pct * self.config.hard_stop_atr_multiplier)
                # Clamp: never wider than 8%, never tighter than 3%
                effective_hard_stop = max(self.config.max_hard_stop_pct, atr_hard_stop)
                effective_hard_stop = min(self.config.min_hard_stop_pct, effective_hard_stop)
            else:
                # Fallback: use fixed 8% if no ATR data yet
                effective_hard_stop = self.config.max_hard_stop_pct

            if plpc <= effective_hard_stop:
                reason = f"Hard stop (ATR): {plpc:.1%} (limit {effective_hard_stop:.1%})"
                trades.append({
                    "symbol": symbol,
                    "qty": qty,
                    "action": "SELL",
                    "reason": reason,
                })
                logger.warning(f"STOP LOSS: {symbol} at {plpc:.1%} (ATR stop {effective_hard_stop:.1%})")
                self.record_stop_out(symbol, reason)
                continue

            # 1b. VWAP-based stop (new with Alpaca paid data)
            if self.config.vwap_stop_enabled:
                vwap = pos.get("daily_vwap") or pos.get("intraday_vwap")
                if vwap and vwap > 0 and current > 0:
                    vwap_deviation = (current - vwap) / vwap
                    if vwap_deviation <= self.config.vwap_stop_buffer_pct:
                        reason = f"VWAP stop: {vwap_deviation:.1%} below VWAP ${vwap:.2f}"
                        trades.append({
                            "symbol": symbol,
                            "qty": qty,
                            "action": "SELL",
                            "reason": reason,
                        })
                        logger.warning(f"VWAP STOP: {symbol} at {vwap_deviation:.1%} below VWAP ${vwap:.2f}")
                        self.record_stop_out(symbol, reason)
                        continue

            # 2. Trailing stop — pure ATR-based (2.0x ATR from peak)
            # No longer capped by fixed 10% — let ATR fully drive it
            atr_pct = self.position_atr_pct.get(symbol)
            if atr_pct and atr_pct > 0:
                atr_trailing = -(atr_pct * self.config.trailing_stop_atr_multiplier)
                # Clamp: never wider than 10%, never tighter than 3%
                effective_trailing = max(-0.10, atr_trailing)
                effective_trailing = min(-0.03, effective_trailing)
            else:
                effective_trailing = self.config.trailing_stop_pct  # fallback -10%

            # VWAP-enhanced trailing: tighten stop if below VWAP
            if self.config.vwap_trailing_enabled and self.config.vwap_stop_enabled:
                vwap = pos.get("daily_vwap")
                if vwap and vwap > 0 and current < vwap:
                    # Below VWAP — tighten the trailing stop by 1%
                    effective_trailing = max(effective_trailing - 0.01, -0.05)

            if peak > 0 and current > 0:
                drawdown_from_peak = (current - peak) / peak
                if drawdown_from_peak <= effective_trailing:
                    reason = f"Trailing stop: {drawdown_from_peak:.1%} from peak ${peak:.2f} (limit {effective_trailing:.1%})"
                    trades.append({
                        "symbol": symbol,
                        "qty": qty,
                        "action": "SELL",
                        "reason": reason,
                    })
                    logger.warning(f"TRAILING STOP: {symbol} at {drawdown_from_peak:.1%} from peak ${peak:.2f} (limit {effective_trailing:.1%})")
                    self.record_stop_out(symbol, reason)
                    continue

            # 3. Full profit exit
            if plpc >= self.config.full_exit_profit_pct:
                trades.append({
                    "symbol": symbol,
                    "qty": qty,
                    "action": "SELL",
                    "reason": f"Full profit take: {plpc:.1%} (target {self.config.full_exit_profit_pct:.1%})",
                })
                logger.info(f"PROFIT FULL EXIT: {symbol} at {plpc:.1%}")
                continue

            # 4. Profit trim
            if plpc >= self.config.trim_profit_pct:
                trim_qty = max(1, qty // 3)
                trades.append({
                    "symbol": symbol,
                    "qty": trim_qty,
                    "action": "SELL",
                    "reason": f"Trim profit: {plpc:.1%} (target {self.config.trim_profit_pct:.1%}), selling {trim_qty}/{qty}",
                })
                logger.info(f"PROFIT TRIM: {symbol} at {plpc:.1%}, sell {trim_qty}")

        return trades

    # ------------------------------------------------------------------
    # Cash-raising: proactively trim weakest positions when cash < floor
    # ------------------------------------------------------------------

    def check_cash_raise(self, portfolio_data: Dict, signals: List[Dict] = None) -> List[Dict]:
        """When cash is below the dynamic floor, trim the weakest positions
        to restore cash above the floor.

        Rationale: Rather than blocking all activity when cash is low, the bot
        selectively trims positions it's least bullish on (lowest readiness scores
        from the signal engine). This keeps the portfolio active and ensures
        cash is always available for better opportunities.

        Rules:
        - Only triggers when cash < dynamic floor
        - Only trims positions with readiness < threshold (default 50)
        - Skips positions worth less than min_position_value
        - Max N trims per cycle to avoid over-selling
        - Skips positions already flagged for exit by check_exits/concentration
        """
        if not self.config.cash_raise_enabled:
            return []

        trades = []
        pv = portfolio_data.get("account", {}).get("portfolio_value", 0)
        cash = portfolio_data.get("account", {}).get("cash", 0)

        if pv <= 0:
            return trades

        cash_floor = self._cash_floor(pv)
        shortfall = cash_floor - cash

        if shortfall <= 0:
            return []  # cash is above floor, nothing to do

        logger.info(f"CASH RAISE: cash ${cash:,.2f} below floor ${cash_floor:,.2f}, shortfall ${shortfall:,.2f}")

        # Build readiness lookup from signals
        readiness_map: Dict[str, float] = {}
        if signals:
            for s in signals:
                readiness_map[s.get("symbol", "")] = s.get("readiness_score", 50.0)

        # Rank positions by readiness (lowest first), then by P&L (worst first)
        positions = portfolio_data.get("positions", [])
        candidates = []
        for pos in positions:
            symbol = pos.get("symbol")
            qty = pos.get("qty", 0)
            mv = pos.get("market_value", 0)
            plpc = pos.get("unrealized_plpc", 0) / 100

            if qty <= 0 or mv < self.config.cash_raise_min_position_value:
                continue

            readiness = readiness_map.get(symbol, 50.0)
            # Skip positions the bot is bullish on
            if readiness >= self.config.cash_raise_readiness_threshold:
                continue

            # Skip positions in profit by more than 15% — let profit-taking handle those
            if plpc > 0.15:
                continue

            candidates.append({
                "symbol": symbol,
                "qty": qty,
                "market_value": mv,
                "readiness": readiness,
                "plpc": plpc,
                "score": readiness + plpc * 100,  # combined: low readiness + low P&L = lowest score
            })

        # Sort by score ascending (worst first)
        candidates.sort(key=lambda c: c["score"])

        if not candidates:
            logger.info(f"CASH RAISE: no eligible positions to trim (all have high readiness or are too small)")
            return []

        # Trim from the weakest until we've covered the shortfall
        remaining_shortfall = shortfall
        trims = 0
        for cand in candidates:
            if remaining_shortfall <= 0 or trims >= self.config.cash_raise_max_trims_per_cycle:
                break

            symbol = cand["symbol"]
            qty = cand["qty"]
            mv = cand["market_value"]
            price = mv / qty if qty > 0 else 0

            if price <= 0:
                continue

            # Calculate how many shares to sell to cover the shortfall
            # Sell at most 25% of the position, or enough to cover shortfall, whichever is less
            max_trim_qty = max(1, qty // 4)  # 25% of position
            needed_qty = math.ceil(remaining_shortfall / price)
            trim_qty = min(max_trim_qty, needed_qty, qty)

            if trim_qty < 1:
                continue

            # Anti-churn: no dust trims — bump to min notional (capped at full position)
            if trim_qty * price < self.config.min_trim_notional and trim_qty < qty:
                trim_qty = min(qty, max(trim_qty, math.ceil(self.config.min_trim_notional / price)))

            trim_value = trim_qty * price
            trades.append({
                "symbol": symbol,
                "qty": trim_qty,
                "action": "SELL",
                "reason": (
                    f"Cash raise: trim {trim_qty}/{qty} of {symbol} "
                    f"(readiness {cand['readiness']:.1f}, P&L {cand['plpc']:+.1%}) "
                    f"to restore ${trim_value:,.0f} cash above ${cash_floor:,.0f} floor"
                ),
            })
            logger.info(f"CASH RAISE: trim {symbol} {trim_qty} shares (${trim_value:,.0f}) "
                        f"readiness={cand['readiness']:.1f} pnl={cand['plpc']:+.1%}")

            remaining_shortfall -= trim_value
            trims += 1

        if trades:
            logger.info(f"CASH RAISE: {len(trades)} trims to raise ${shortfall - remaining_shortfall:,.2f}")
        else:
            logger.info(f"CASH RAISE: could not raise cash — all positions too small or too bullish")

        return trades

    # ------------------------------------------------------------------
    # Rotation: rebalance from low-readiness to high-readiness positions
    # ------------------------------------------------------------------

    def check_rotation(self, portfolio_data: Dict, signals: List[Dict] = None, failed_buy_symbols: Optional[set] = None) -> List[Dict]:
        """Trim overweight low-readiness positions to free capital for high-readiness entries.

        Unlike check_cash_raise (which only fires when cash < floor), this runs
        every scan cycle to keep capital allocated to the bot's best ideas.

        Rules:
        - Only trims positions > rotation_min_position_pct (5% of portfolio)
        - Only trims positions with readiness < 55 (weak conviction)
        - Only fires if there are eligible buy candidates with readiness >= 70
        - Requires at least rotation_readiness_gap (15) between trim target and buy target
        - Max 2 trims per cycle
        - Skips positions already flagged by check_exits/concentration
        - Skips buy targets in failed_buy_symbols
        - Only fires once per cooldown period to avoid over-trading
        """
        if not self.config.rotation_enabled:
            return []

        trades = []
        pv = portfolio_data.get("account", {}).get("portfolio_value", 0)
        if pv <= 0:
            return trades

        # Cooldown check
        if self.last_rotation_time is not None:
            hours_since = (datetime.now(timezone.utc) - self.last_rotation_time).total_seconds() / 3600
            if hours_since < self.config.rotation_cooldown_hours:
                return []

        if not signals:
            return trades

        failed_buy_symbols = failed_buy_symbols or set()

        # Build readiness lookup
        readiness_map: Dict[str, float] = {}
        for s in signals:
            readiness_map[s.get("symbol", "")] = s.get("readiness_score", 50.0)

        # Find high-readiness buy candidates not currently held.
        # Exclude symbols in stop-out cooldown (they can't be bought anyway) so
        # rotation doesn't trim positions to fund a buy that will be blocked.
        held_symbols = {p.get("symbol") for p in portfolio_data.get("positions", [])}
        best_unheld = [
            (s.get("symbol"), s.get("readiness_score", 0))
            for s in signals
            if s.get("symbol") not in held_symbols
            and s.get("symbol") not in failed_buy_symbols
            and not self.in_stop_cooldown(s.get("symbol", ""))
            and s.get("entry_eligible", False)
            and s.get("readiness_score", 0) >= 70
        ]
        best_unheld.sort(key=lambda x: x[1], reverse=True)

        if not best_unheld:
            return []  # no strong buy candidates, no need to rotate

        top_buy_readiness = best_unheld[0][1]

        # Find overweight low-readiness positions to trim
        positions = portfolio_data.get("positions", [])
        candidates = []
        for pos in positions:
            symbol = pos.get("symbol")
            qty = pos.get("qty", 0)
            mv = pos.get("market_value", 0)
            pos_pct = mv / pv
            readiness = readiness_map.get(symbol, 50.0)

            if qty <= 0:
                continue  # short/anomalous — not rotation material
            # Only trim overweight positions (> 5% of portfolio)
            if pos_pct < self.config.rotation_min_position_pct:
                continue
            # Only trim low-readiness positions
            if readiness >= 55:
                continue
            # Check readiness gap — buy target must be meaningfully stronger
            if (top_buy_readiness - readiness) < self.config.rotation_readiness_gap:
                continue

            candidates.append({
                "symbol": symbol,
                "qty": qty,
                "market_value": mv,
                "pos_pct": pos_pct,
                "readiness": readiness,
                "gap": top_buy_readiness - readiness,
            })

        if not candidates:
            return []

        # Sort by worst readiness first
        candidates.sort(key=lambda c: c["readiness"])

        logger.info(
            f"ROTATION: {len(candidates)} overweight low-readiness positions, "
            f"top buy candidate {best_unheld[0][0]} (readiness {top_buy_readiness:.1f})"
        )

        self.last_rotation_time = datetime.now(timezone.utc)

        # Trim up to rotation_max_trims_per_cycle
        for i, cand in enumerate(candidates[:self.config.rotation_max_trims_per_cycle]):
            symbol = cand["symbol"]
            qty = cand["qty"]
            mv = cand["market_value"]
            price = mv / qty if qty > 0 else 0

            # Trim 20% of position (or at least rotation_min_trim_pct)
            trim_qty = max(1, int(qty * 0.20))
            # Anti-churn: no dust trims
            if trim_qty * price < self.config.min_trim_notional and trim_qty < qty:
                trim_qty = min(qty, max(trim_qty, math.ceil(self.config.min_trim_notional / price)))
            trim_value = trim_qty * price

            trades.append({
                "symbol": symbol,
                "qty": trim_qty,
                "action": "SELL",
                "reason": (
                    f"Rotation: trim {symbol} (readiness {cand['readiness']:.1f}, "
                    f"{cand['pos_pct']:.1f}% of portfolio) to fund "
                    f"{best_unheld[0][0]} (readiness {top_buy_readiness:.1f})"
                ),
            })
            logger.info(
                f"ROTATION: trim {symbol} {trim_qty} shares (${trim_value:,.0f}) "
                f"readiness={cand['readiness']:.1f} -> fund {best_unheld[0][0]} readiness={top_buy_readiness:.1f}"
            )

        return trades

    # ------------------------------------------------------------------
    # Rebalancing / trimming oversized positions
    # ------------------------------------------------------------------

    def check_concentration(self, portfolio_data: Dict, force: bool = False) -> List[Dict]:
        """Trim oversized positions and sectors anytime a trigger is hit."""
        trades = []
        pv = portfolio_data.get("account", {}).get("portfolio_value", 0)
        if pv <= 0:
            return trades

        positions = portfolio_data.get("positions", [])
        trimmed_symbols = set()

        # Sector aggregates
        sector_mv: Dict[str, float] = {}
        for pos in positions:
            sector = pos.get("sector", "Other")
            sector_mv[sector] = sector_mv.get(sector, 0.0) + pos.get("market_value", 0)

        # Single-stock concentration first.
        # Anti-churn: only trim when ABOVE cap + band, trim to BELOW cap,
        # enforce min trim notional and a per-symbol cooldown. Prevents the
        # 1-share "10.0% > 10.0%" dust-trim spam seen the week of 2026-07-13.
        cap = self.config.max_single_position_pct
        band = self.config.concentration_trim_band
        target_pct = cap - self.config.concentration_trim_target_buffer
        for pos in positions:
            symbol = pos.get("symbol")
            qty = pos.get("qty", 0)
            mv = pos.get("market_value", 0)
            if qty <= 0 or mv <= 0:
                continue

            pos_pct = mv / pv
            trigger = cap * self.config.concentration_trim_trigger + band
            if pos_pct > trigger:
                if self._trim_on_cooldown(symbol):
                    logger.debug(f"Trim cooldown active for {symbol}; skipping concentration trim")
                    continue
                target_mv = pv * target_pct
                excess = mv - target_mv
                price = mv / qty
                trim_qty = max(1, int((excess / price)))
                if trim_qty * price < self.config.min_trim_notional and trim_qty < qty:
                    trim_qty = min(qty, math.ceil(self.config.min_trim_notional / price))
                trades.append({
                    "symbol": symbol,
                    "qty": trim_qty,
                    "action": "SELL",
                    "reason": f"Concentration trim: position {pos_pct:.1%} > trigger {trigger:.1%}, target {target_pct:.1%}",
                })
                logger.info(f"CONCENTRATION TRIM: {symbol} {trim_qty} shares")
                self._record_trim(symbol)
                trimmed_symbols.add(symbol)

        # Sector concentration: only trim positions not already trimmed
        sector_cap = self.config.max_sector_pct
        sector_band = 0.01  # 1pp hysteresis on sector trims
        for pos in positions:
            symbol = pos.get("symbol")
            if symbol in trimmed_symbols:
                continue
            qty = pos.get("qty", 0)
            mv = pos.get("market_value", 0)
            sector = pos.get("sector", "Other")
            if qty <= 0 or mv <= 0:
                continue

            sec_pct = sector_mv.get(sector, 0) / pv
            sector_trigger = sector_cap * self.config.concentration_trim_trigger + sector_band
            if sec_pct > sector_trigger:
                if self._trim_on_cooldown(symbol):
                    logger.debug(f"Trim cooldown active for {symbol}; skipping sector trim")
                    continue
                trim_qty = max(1, qty // 4)
                price = mv / qty
                if trim_qty * price < self.config.min_trim_notional and trim_qty < qty:
                    trim_qty = min(qty, math.ceil(self.config.min_trim_notional / price))
                trades.append({
                    "symbol": symbol,
                    "qty": trim_qty,
                    "action": "SELL",
                    "reason": f"Sector trim: {sector} {sec_pct:.1%} > trigger {sector_trigger:.1%}",
                })
                logger.info(f"SECTOR TRIM: {symbol} {trim_qty} shares ({sector})")
                self._record_trim(symbol)
                # reduce sector_mv so we don't over-trim
                sector_mv[sector] -= mv * (trim_qty / qty)

        return trades

    def check_high_beta_basket(self, portfolio_data: dict, high_beta_symbols: set) -> list:
        """Trim high-beta positions if deployed capital in the high-beta basket exceeds the configured cap."""
        trades = []
        if not self.config.high_beta_basket_cap_enabled or not high_beta_symbols:
            return trades

        account = portfolio_data.get("account", {})
        pv = account.get("portfolio_value", 0)
        equity = account.get("equity", pv)
        deployed = equity - account.get("cash", 0)
        if deployed <= 0 or pv <= 0:
            return trades

        positions = portfolio_data.get("positions", [])
        high_beta_mv = sum(p.get("market_value", 0) for p in positions if p.get("symbol") in high_beta_symbols)
        high_beta_pct = high_beta_mv / deployed if deployed > 0 else 0.0
        cap = self.config.max_high_beta_deployed_pct
        if high_beta_pct <= cap:
            return trades

        excess_mv = high_beta_mv - deployed * cap
        hb_positions = [p for p in positions if p.get("symbol") in high_beta_symbols and p.get("market_value", 0) > 0 and p.get("qty", 0) > 0]
        hb_positions.sort(key=lambda p: p.get("market_value", 0), reverse=True)

        for pos in hb_positions:
            if excess_mv <= 0:
                break
            symbol = pos.get("symbol")
            qty = pos.get("qty", 0)
            mv = pos.get("market_value", 0)
            price = mv / qty if qty > 0 else 0
            trim_qty = max(1, int(min(qty, excess_mv / price)) if price > 0 else 1)
            trades.append({
                "symbol": symbol,
                "qty": trim_qty,
                "action": "SELL",
                "reason": f"High-beta basket trim: {high_beta_pct:.1%} deployed vs {cap:.1%} cap",
            })
            logger.info(f"HIGH-BETA TRIM: {symbol} {trim_qty} shares ({high_beta_pct:.1%} > {cap:.1%})")
            excess_mv -= trim_qty * price

        return trades
