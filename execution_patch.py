"""
Execution Optimization patch for trading_bot.py

Adds:
  - Limit orders at bid/ask midpoint (or last price fallback)
  - TWAP-style split for large orders (configurable threshold)
  - Slippage tracking per trade

Apply to AlpacaClient.submit_order() and related methods.
"""

# In AlpacaClient class, replace submit_order with:

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        dry_run: bool = False,
        use_limit: bool = True,
        twap_threshold: int = 100,
    ) -> Optional[str]:
        if dry_run:
            logger.info(f"DRY RUN {side.upper()} {qty} {symbol}")
            return "dry-run"
        if qty <= 0:
            return None

        side_lower = side.lower()
        orders = []

        # TWAP split for large orders
        if qty > twap_threshold:
            chunks = self._twap_chunks(qty, twap_threshold)
            logger.info(f"TWAP: splitting {side} {symbol} into {len(chunks)} chunks")
        else:
            chunks = [qty]

        order_ids = []
        for chunk in chunks:
            payload = self._build_order_payload(symbol, chunk, side_lower, use_limit=use_limit)
            if payload is None:
                continue
            try:
                r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=15)
                r.raise_for_status()
                order_ids.append(r.json().get("id", "unknown"))
            except Exception as e:
                logger.error(f"Failed to submit {side} order for {symbol}: {e}")
                return None

            # Brief pause between TWAP chunks
            if len(chunks) > 1 and chunk != chunks[-1]:
                import time
                time.sleep(1)

        return order_ids[0] if order_ids else None

    def _twap_chunks(self, qty: int, threshold: int) -> List[int]:
        """Split a large order into roughly equal chunks."""
        import math
        n = math.ceil(qty / threshold)
        base = qty // n
        remainder = qty % n
        chunks = [base + 1] * remainder + [base] * (n - remainder)
        return chunks

    def _build_order_payload(self, symbol: str, qty: int, side: str, use_limit: bool = True) -> Optional[Dict]:
        if not use_limit:
            return {
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            }

        # Get midpoint price
        midpoint = self.get_latest_quote(symbol)
        if midpoint is None or midpoint <= 0:
            # Fallback to market order
            return {
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            }

        # Round limit price to 2 decimals
        limit_price = round(midpoint, 2)

        return {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(limit_price),
        }

    def get_latest_quote(self, symbol: str) -> Optional[float]:
        """Fetch latest bid/ask midpoint for limit orders."""
        try:
            r = self.session.get(
                f"{self.data_url}/v2/stocks/quotes/latest",
                params={"symbols": symbol, "feed": "sip"},
                timeout=15,
            )
            r.raise_for_status()
            quote = r.json().get("quotes", {}).get(symbol, {})
            bid = quote.get("bp") or 0
            ask = quote.get("ap") or 0
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            return quote.get("p") or quote.get("ap") or quote.get("bp")
        except Exception as e:
            logger.warning(f"Could not get quote for {symbol}: {e}")
            return None


# In _log_trade(), add slippage tracking:
# After determining the executed price (if available from order response),
# compare to expected price and store:
#   "slippage_bps": (executed_price - expected_price) / expected_price * 10000
