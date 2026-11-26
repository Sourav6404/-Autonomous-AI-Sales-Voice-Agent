import httpx
import sys

BASE_URL = "http://127.0.0.1:8000"

urls_to_check = [
    ("/v1/health/live", "Health Live Probe"),
    ("/v1/health/ready", "Health Ready Probe"),
    ("/", "Login / Main Dashboard"),
    ("/admin-dashboard", "Admin Dashboard"),
    ("/receptionist-dashboard", "Receptionist Portal"),
    ("/sales-dashboard", "Sales Employee Dashboard"),
    ("/voice-console", "Voice Console"),
    ("/knowledge-console", "Knowledge Base Console"),
]

def main():
    print("Verifying URLs on:", BASE_URL)
    all_ok = True
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        for path, desc in urls_to_check:
            try:
                res = client.get(path)
                status = res.status_code
                print(f"[{status}] {desc:<30} -> {BASE_URL}{path} ({len(res.content)} bytes)")
                if status not in (200, 204):
                    all_ok = False
            except Exception as e:
                print(f"[ERR] {desc:<30} -> {BASE_URL}{path} : {e}")
                all_ok = False
                
    if not all_ok:
        sys.exit(1)
    print("ALL URLS VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
