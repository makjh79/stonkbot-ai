import subprocess, json, sys
result = subprocess.run(["python3", "/opt/stonk-ai/comprehensive_monitor.py", "--dry-run"], capture_output=True, text=True, cwd="/opt/stonk-ai")
print("exit:", result.returncode)
print("--- output ---")
print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
