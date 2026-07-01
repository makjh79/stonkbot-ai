import re

# Patch dynamic_watchlist_manager.py
dwm_path = "/opt/stonk-ai/dynamic_watchlist_manager.py"
dwm_text = open(dwm_path).read()
if "heartbeat_tracker" not in dwm_text:
    dwm_text = dwm_text.replace(
        "if __name__ == \"__main__\":\n    update_watchlist()",
        """def _record_heartbeat():
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/python3", "/opt/stonk-ai/heartbeat_tracker.py", "dynamic_watchlist_manager"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


if __name__ == "__main__":
    update_watchlist()
    _record_heartbeat()"""
    )
    open(dwm_path, "w").write(dwm_text)
    print("patched dynamic_watchlist_manager.py")

# Patch update_iv_summaries.py
iv_path = "/opt/stonk-ai/update_iv_summaries.py"
iv_text = open(iv_path).read()
if "heartbeat_tracker" not in iv_text:
    iv_text = iv_text.replace(
        "if __name__ == \"__main__\":\n    main()",
        """def _record_heartbeat():
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/python3", "/opt/stonk-ai/heartbeat_tracker.py", "update_iv_summaries"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
    _record_heartbeat()"""
    )
    open(iv_path, "w").write(iv_text)
    print("patched update_iv_summaries.py")

# Patch comprehensive_monitor.py
mon_path = "/opt/stonk-ai/comprehensive_monitor.py"
mon_text = open(mon_path).read()
if "heartbeat_tracker" not in mon_text:
    mon_text = mon_text.replace(
        "if __name__ == \"__main__\":\n    sys.exit(main())",
        """def _record_heartbeat():
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/python3", "/opt/stonk-ai/heartbeat_tracker.py", "comprehensive_monitor"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


if __name__ == \"__main__\":
    code = main()
    _record_heartbeat()
    sys.exit(code)"""
    )
    # Also fix signals.json max_age and make IV heartbeat market-aware
    mon_text = mon_text.replace(
        '        "signals.json": 600,            # 10 min',
        '        "signals.json": 1200,           # 20 min slack (signal engine refreshes ~every 15 min)'
    )
    # Update heartbeat expectations: IV only runs market hours
    old_expected = """    expected = {
        \"stonk_health_check\": 10,
        \"dynamic_watchlist_manager\": 10,
        \"sync_alpaca_trades\": 10,
        \"update_iv_summaries\": 30,
        \"daily_liquidity_report_am\": 300,
        \"daily_liquidity_report_pm\": 300,
        \"comprehensive_monitor\": 20,
        \"signal_enricher_full_am\": 1500,
        \"signal_enricher_full_pm\": 1500,
        \"watchlist_feedback\": 1500,
        \"fetch_price_history\": 1500,
        \"vps_memory_maintenance\": 1500,
        \"analyze_options_skew_signal\": 1500,
    }"""
    new_expected = """    expected = {
        \"stonk_health_check\": 10,
        \"dynamic_watchlist_manager\": 10,
        \"sync_alpaca_trades\": 10,
        # IV summaries only run 9-16 UTC weekdays; allow large slack otherwise
        \"update_iv_summaries\": 30 if is_market_hours() else 2880,
        \"daily_liquidity_report_am\": 300,
        \"daily_liquidity_report_pm\": 300,
        \"comprehensive_monitor\": 20,
        \"signal_enricher_full_am\": 1500,
        \"signal_enricher_full_pm\": 1500,
        \"watchlist_feedback\": 1500,
        \"fetch_price_history\": 1500,
        \"vps_memory_maintenance\": 1500,
        \"analyze_options_skew_signal\": 1500,
    }"""
    if old_expected in mon_text:
        mon_text = mon_text.replace(old_expected, new_expected)
        print("updated heartbeat expectations")
    else:
        print("could not find expected block")
    open(mon_path, "w").write(mon_text)
    print("patched comprehensive_monitor.py")
