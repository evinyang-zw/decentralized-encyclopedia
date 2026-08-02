"""停止所有 Agent 进程。"""
import subprocess
import sys


def main():
    ports = [8000, 8001, 8002, 8003, 8004, 8005, 8006, 8010]
    for port in ports:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    print(f"Killed process {pid} on port {port}")
        except Exception:
            pass
    print("All services stopped.")


if __name__ == "__main__":
    main()
