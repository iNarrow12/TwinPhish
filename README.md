# TwinPhish

**A dual-vector phishing proof-of-concept that chains mr.d0x's Browser-in-the-Browser (BitB) attack with his noVNC 2FA-bypass technique.**

TwinPhish spins up a disposable Firefox container behind noVNC, exposes it through a Cloudflare Quick Tunnel, and wraps the whole remote desktop inside a pixel-perfect fake browser window. The target believes they are typing into a native Google sign-in popup; in reality they are driving a remote Firefox in kiosk mode while the operator watches the same session.

> **EDUCATIONAL AND AUTHORIZED TESTING USE ONLY.**
> This project exists to demonstrate and research two publicly documented phishing techniques. It is intended strictly for use in controlled lab environments, security awareness training, and engagements where you have **explicit written permission** from the system owner. Running this against anyone without consent is illegal in most jurisdictions and is not condoned by the author. You are solely responsible for how you use this code.

---

## Table of contents

- [Overview](#overview)
- [The two concepts](#the-two-concepts)
  - [1. Browser-in-the-Browser (BitB)](#1-browser-in-the-browser-bitb)
  - [2. Credential theft and 2FA bypass with noVNC](#2-credential-theft-and-2fa-bypass-with-novnc)
- [How TwinPhish combines them](#how-twinphish-combines-them)
- [Architecture](#architecture)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Usage](#usage)
  - [Orchestrator: run.py](#orchestrator-runpy)
  - [Backend: novnc/app.py](#backend-novncappy)
  - [Flags reference](#flags-reference)
- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Component reference](#component-reference)
- [Configuration](#configuration)
- [Cleanup](#cleanup)
- [Limitations](#limitations)
- [Detection and mitigation](#detection-and-mitigation)
- [Legal and ethical notice](#legal-and-ethical-notice)
- [Credits](#credits)
- [References](#references)
- [License](#license)

---

## Overview

Classic phishing has one weak point: the URL. Users are trained to "check the address bar", so attackers spend enormous effort on lookalike domains and TLS certificates.

TwinPhish instead attacks the assumption itself:

1. **BitB** draws a fake Chrome/Google-authentication window with HTML, CSS, and an SVG padlock. The address bar inside the fake window displays `accounts.google.com`, even though the real page is hosted on `*.trycloudflare.com`.
2. The iframe inside that fake window points at a **noVNC** session. The target is not filling a local HTML form; they are operating a real Firefox instance running in kiosk mode on the operator's machine, pre-navigated to the real login page.

Because the session is real, everything downstream works: password managers, WebAuthn prompts, device checks, and post-login 2FA flows. Credentials are not relayed or replayed by a proxy, so MITM detections such as those that break Evilginx-style phishlets do not apply. The operator simply watches (or logs) the session, and the authenticated cookies stay in the container profile.

This repository is a proof-of-concept harness for that chain. It is not a production phishing kit and deliberately omits campaign management, per-target session isolation, and delivery automation.

---

## The two concepts

### 1. Browser-in-the-Browser (BitB)

Source: [Browser In The Browser (BITB) Attack](https://mrd0x.com/browser-in-the-browser-phishing-attack/) by mr.d0x (March 2022).

Many login flows open a popup that the user trusts implicitly: "Sign in with Google", Microsoft, Apple, and so on. BitB replicates that popup in plain HTML/CSS:

- a fake title bar with the provider logo and window controls;
- a fake URL bar with a padlock and the **legitimate-looking domain**;
- an iframe pointed at the attacker-controlled page.

When the user clicks "Sign in", a window that is nearly indistinguishable from the real one appears. The visible URL is attacker-controlled and can be set to `accounts.google.com`, while the underlying origin remains the attacker's site. Hovering a link is not a reliable defense either, since JavaScript can return `false` from an `onclick` handler and suppress the real `href` navigation.

Key properties:

- No browser vulnerability is required; it abuses UI trust.
- The fake window can be draggable, resizable, and closable to feel authentic.
- The URL bar content is cosmetic and independent of the iframe origin.

### 2. Credential theft and 2FA bypass with noVNC

Source: [Steal Credentials & Bypass 2FA Using noVNC](https://mrd0x.com/bypass-2fa-using-novnc/) by mr.d0x (February 2022).

noVNC is an HTML5 VNC client. If a remote browser runs in kiosk mode, a visitor can drive it from a normal web page and never realize they are looking at a remote desktop.

The technique:

1. Host a machine with noVNC and a browser in kiosk mode.
2. Pre-navigate kiosk Firefox to the target login page (for example `accounts.google.com`).
3. Send the noVNC URL to the target. With `?autoconnect=true&resize=scale` the VNC control UI is bypassed and the page scales like a normal website.
4. Hide noVNC chrome (control bar, status text, transition screen) so only the kiosk browser remains visible.
5. Capture what happens next by any means available on the operator's own machine: a keylogger userscript, network capture, VNC recording, or simply reading cookies from the profile after the user finishes.

Why this bypasses 2FA:

- The login happens on the real site in a real browser, so the second factor is completed normally by the victim.
- The resulting session lives in the operator-controlled browser profile; the operator can extract cookies or keep interacting with the authenticated session.
- There is no reverse proxy to fingerprint, because the traffic never passes through one.

mr.d0x also documented multi-session scaling (`&port=`), `resize=remote` auto-scaling, disabling the screen lock, and the risks of exposing a live desktop (never use root, keep nothing sensitive on the host).

---

## How TwinPhish combines them

TwinPhish merges the two ideas into one link:

```
Target clicks https://<random>.trycloudflare.com/bitb.html
        |
        v
attacker_index.html  (decoy: "You have received a secure document")
        |
        v
bitb_payload.js renders a fake Chrome window with:
  - Google logo, title "Sign in - Google Accounts"
  - padlock + address bar showing accounts.google.com
  - an iframe -> /?autoconnect=true&resize=scale
        |
        v
noVNC session -> Firefox kiosk -> real accounts.google.com login
        |
        v
Victim completes password + 2FA on the operator's browser
        |
        v
Operator reads keystrokes (userscript) and/or session cookies from the profile
```

The BitB layer supplies the **visual trust** ("the URL says Google"). The noVNC layer supplies a **real, interactive, authenticated session**. Neither half is novel on its own; the combination is what makes the lure convincing end to end.

---

## Architecture

```
+--------------------------------------------------------------+
|                        Host / operator                        |
|                                                              |
|  run.py  (orchestrator)                                      |
|    |                                                         |
|    |-- starts --> python3 novnc/app.py mobile -tun           |
|    |                  |                                      |
|    |                  |-- docker run jlesage/firefox         |
|    |                  |     name: firefox-kiosk              |
|    |                  |     port: 80 -> 5800 (noVNC)         |
|    |                  |     FF_KIOSK=1, FF_OPEN_URL=...      |
|    |                  |     DISPLAY_WIDTH/HEIGHT (mobile)    |
|    |                  |                                      |
|    |                  |-- cloudflared quick tunnel           |
|    |                        https://<random>.trycloudflare.com
|    |                                                         |
|    |-- docker cp bitb/* --> firefox-kiosk:/opt/noVNC/        |
|                                                              |
|  optional: novnc/server.py  <--  keylogger.js (userscript)   |
+--------------------------------------------------------------+
                           |
                           |  public URL
                           v
+--------------------------------------------------------------+
| Target browser                                               |
|   /bitb.html -> fake Chrome popup -> iframe -> noVNC canvas  |
+--------------------------------------------------------------+
```

---

## Features

- One-command orchestration for the combined attack (`run.py --bitb`).
- Full standalone noVNC backend with `core`, `desktop`, and `mobile` modes.
- Mobile kiosk mode with device-sized viewports and a mobile User-Agent override.
- Automatic Cloudflare Quick Tunnel creation and public URL extraction.
- Automatic BitB asset injection into the running container with `docker cp`.
- noVNC chrome removal (control bar, status, transition) for a seamless canvas.
- Fake Chrome window with Google branding, padlock, draggable title bar, and maximize/restore.
- Optional keystroke capture userscript and local listener.
- Transparent sudo detection for Docker access.
- Clean stop/reset commands that remove containers and optionally wipe the Firefox profile.

---

## Requirements

| Requirement | Notes |
| --- | --- |
| Linux host | Tested on Linux. Docker, `sudo`, and file paths assume a Linux layout. |
| Python 3.9+ | `run.py` and `novnc/app.py` are Python 3 scripts. |
| Docker Engine | The backend container needs a working Docker daemon. |
| `jlesage/firefox` image | Pulled automatically on first run if absent. |
| `cloudflared` | Required for `-tun/--tunnel`. Must be in `PATH` or a common install path. |
| `rich` (Python package) | Used by `novnc/app.py` for terminal output. Install with `pip install rich`. |
| Port 80 free (default) | The default host port is 80, which may require root or sudo. |
| Internet access | Needed to reach the target login site from inside the container and to create the tunnel. |

Optional, for keystroke capture:

- Tampermonkey (or any userscript manager) in the kiosk browser.
- Python 3 on the host to run `novnc/server.py`.

---

## Installation

```bash
git clone <this-repository> TwinPhish
cd TwinPhish

python3 -m venv .venv
source .venv/bin/activate
pip install rich

# Verify prerequisites
docker info
cloudflared --version
```

If Docker requires elevation, `app.py` will detect it and either use passwordless sudo or prompt once for credentials.

Pull the browser image ahead of time to avoid a delay during a demo:

```bash
docker pull jlesage/firefox
```

---

## Quick start

Standard noVNC-only session (the classic 2FA-bypass technique):

```bash
python3 run.py desktop -l google -tun
```

Combined BitB + noVNC session:

```bash
python3 run.py --bitb -l google
```

The orchestrator prints the public URL to share:

```
============================================================
 TWINPHISH READY! Send this link to the target:
 https://<random>.trycloudflare.com/bitb.html
============================================================
```

Stop everything at any time:

```bash
python3 novnc/app.py stop -y
```

---

## Usage

### Orchestrator: run.py

`run.py` is a thin wrapper. Without `--bitb` it simply forwards every argument to `novnc/app.py`, so all backend modes are available.

```bash
python3 run.py desktop -l google -tun          # noVNC only, desktop kiosk
python3 run.py mobile -l x -s iphone-14-pro-max -tun
python3 run.py core -tun                       # full desktop browser
python3 run.py --bitb -l google                # BitB + noVNC, auto mobile
```

`run.py` options:

| Option | Description |
| --- | --- |
| `--bitb` | Enable the BitB module. Forces mobile kiosk mode, starts the backend, waits for the tunnel URL, injects BitB assets, and prints `/bitb.html`. |
| `-h`, `--help` | Shows the orchestrator help **plus** the full `app.py` help appended. |

Everything else is forwarded to `app.py`. Unknown arguments are passed through untouched.

In `--bitb` mode the orchestrator:

1. Appends `mobile` as the backend subcommand and `-tun` unless a tunnel flag is already present.
2. Appends a Safari/iPhone mobile User-Agent override to `/docker/appdata/firefox/user.js`.
3. Starts `app.py`, streams its output, and extracts the first `https://*.trycloudflare.com` URL.
4. Waits for noVNC to boot, then copies `bitb.html`, `bitb_payload.js`, and `bitb_payload.css` into `/opt/noVNC/` inside the `firefox-kiosk` container.
5. Prints the final lure URL and keeps running until `Ctrl+C`.

### Backend: novnc/app.py

`app.py` manages the Firefox container and the noVNC proxy.

```bash
python3 novnc/app.py <command> [options]
```

Commands:

| Command | Purpose |
| --- | --- |
| `core` | Full desktop Firefox browser (no kiosk target). |
| `desktop` | Desktop kiosk pointed at a URL. |
| `mobile` | Mobile-sized kiosk pointed at a URL. |
| `stop` | Stop and remove the containers (requires `-y`). |
| `reset` | Stop, remove, and wipe the Firefox profile (requires `-y`). |
| `sites` | List preset site keys and exit. |
| `sizes` | List mobile preset sizes and exit. |

The subcommand can be omitted; `app.py` infers it from the flags:

| Flags present | Inferred command |
| --- | --- |
| `-l`/`-u` and no `-s` | `desktop` |
| `-l`/`-u` with `-s` | `mobile` |
| `-s` only | `mobile` |
| Nothing target/size related | `core` |

Examples:

```bash
python3 novnc/app.py core
python3 novnc/app.py core -tun
python3 novnc/app.py desktop -l google
python3 novnc/app.py desktop -l google -tun
python3 novnc/app.py mobile -l x -tun
python3 novnc/app.py mobile -l x --size iphone-14-pro-max
python3 novnc/app.py mobile -u https://example.com/login -s 390x844
python3 novnc/app.py -l google -tun                    # -> desktop
python3 novnc/app.py -u https://x.com -s iphone-12 -tun  # -> mobile
python3 novnc/app.py -tun                              # -> core
python3 novnc/app.py stop -y
python3 novnc/app.py reset -y
```

### Flags reference

Common options (valid for deploy, `stop`, and `reset`):

| Flag | Default | Description |
| --- | --- | --- |
| `-p`, `--port` | `80` | Host port mapped to the noVNC port 5800 in the container. |
| `-d`, `--data` | `/docker/appdata/firefox` | Firefox profile directory mounted at `/config`. |
| `--stop-on-exit` | off | Install SIGINT/SIGTERM handlers that stop containers and the tunnel. |
| `-tun`, `--tunnel` | off | Start a Cloudflare Quick Tunnel for the mapped port. |
| `--script FILE` | none | Declared option for a userscript path. Reserved; the current deploy path does not mount or inject it automatically. |

Target options (`desktop` and `mobile`, mutually exclusive and required):

| Flag | Description |
| --- | --- |
| `-u`, `--url URL` | Custom target URL opened in the kiosk browser. |
| `-l`, `--list NAME` | Preset site key. |

Preset sites:

| Key | Site | URL |
| --- | --- | --- |
| `google` | Google Sign-In | `https://accounts.google.com` |
| `x` | X (Twitter) Sign-In | `https://x.com/i/flow/login` |
| `github` | GitHub Sign-In | `https://github.com/login` |

Mobile sizes (`-s`, `--size`, accepts a preset name or `WxH`):

| Key | Resolution |
| --- | --- |
| `default` | 500x710 |
| `iphone-se` | 375x667 |
| `iphone-12` | 390x844 |
| `iphone-14-pro-max` | 430x932 |
| `pixel-7` | 412x915 |
| `galaxy-s21` | 360x800 |
| `tablet` | 768x1024 |

Confirmation options:

| Flag | Description |
| --- | --- |
| `-y`, `--yes` | Required by `stop` and `reset`; refuses destructive actions otherwise. |

### Optional keystroke capture

The repository includes a Tampermonkey userscript (`novnc/keylogger.js`) and a tiny HTTP listener (`novnc/server.py`).

```bash
python3 novnc/server.py
```

The listener binds `0.0.0.0:3000` and prints captured keys. The userscript posts to `http://172.17.0.1:3000/log-keystrokes`, which is the host address as seen from the default Docker bridge network.

The script sends:

- buffered keystrokes (`<Typing> ...`) after a short idle delay;
- field values on focus timeout, on click-away, and on form submit;
- a final flush on `beforeunload`.

Install it in the kiosk browser through Tampermonkey and adjust `LISTENER_URL` if your Docker network uses a different gateway.

---

## How it works

1. **Container deployment.** `app.py` stops conflicting containers, then runs `jlesage/firefox` detached as `firefox-kiosk`, mapping host port 80 to container port 5800. Kiosk behavior is controlled with `FF_KIOSK=1` and `FF_OPEN_URL=<target>`; mobile mode also sets `DISPLAY_WIDTH`/`DISPLAY_HEIGHT`.
2. **noVNC cleanup.** Inside the container, a `sed` command injects CSS into `/opt/noVNC/index.html` to hide the control bar, status line, panels, and transition screen, leaving only the browser canvas.
3. **Public exposure.** With `-tun`, `cloudflared tunnel --url http://localhost:<port> --no-autoupdate` is launched and its stderr is parsed for the `trycloudflare.com` URL.
4. **Mobile disguise (BitB mode).** `run.py` appends a mobile Safari User-Agent override to Firefox's `user.js`, making the remote browser present itself as an iPhone.
5. **BitB injection.** `run.py` copies the decoy page and payload into the container's noVNC web root. The decoy's button calls `launchBitB()`, which builds the fake window and loads the noVNC session in an iframe with `?autoconnect=true&resize=scale`.
6. **Victim interaction.** The target sees a secure-looking Google window. Typing flows over VNC to the real Firefox. Any 2FA challenge is completed by the victim inside the remote session.
7. **Collection.** The operator can read the live session, capture keystrokes through the userscript, and extract cookies or authenticated state from the container profile at `/docker/appdata/firefox`.

---

## Project structure

```
TwinPhish/
├── run.py                    # Orchestrator: forwards to app.py or runs BitB mode
├── README.md
├── bitb/
│   ├── attacker_index.html   # Decoy landing page ("secure document")
│   ├── bitb_payload.css      # Fake Chrome window styling
│   └── bitb_payload.js       # Builds the fake window, URL bar, and iframe
└── novnc/
    ├── app.py                # Docker + noVNC + Cloudflare tunnel manager
    ├── server.py             # Keystroke listener (port 3000)
    └── keylogger.js          # Tampermonkey userscript
```

---

## Component reference

### `run.py`

- `TwinPhishParser` extends `argparse` so `-h` shows both orchestrator and backend help.
- `docker_cp()` copies files into a container, retrying with `sudo` if needed.
- `inject_mobile_user_agent()` appends a User-Agent override to the Firefox profile.
- `main()` implements the two modes: pass-through and BitB orchestration.

### `novnc/app.py`

- Docker helpers with automatic sudo detection (`detect_sudo`, `docker`, `run_detached`).
- Cloudflare tunnel lifecycle (`start_cloudflare_tunnel`, `stop_cloudflare_tunnel`).
- Argument normalization for shorthand invocations (`normalize_argv`).
- Deploy actions for `core`, `desktop`, and `mobile` (`deploy_core`, `_deploy_kiosk`).
- noVNC UI hiding via an in-container `sed` (`hide_novnc_ui`).
- Profile reset and teardown (`reset_firefox_profile`, `stop_and_remove_all`).

### `bitb/`

- `attacker_index.html` is the lure. It presents a fake "secure document" and a button that calls `launchBitB()`.
- `bitb_payload.js` injects the fake window markup, Google logo SVG, padlock, cosmetic URL path, window controls, drag behavior, and maximize/restore logic. The iframe source is relative (`/?autoconnect=true&resize=scale`), so it works when served from the noVNC root.
- `bitb_payload.css` styles the backdrop, window, title bar, URL bar, and iframe container.

### `novnc/server.py` and `novnc/keylogger.js`

- `server.py` is a minimal `HTTPServer` that accepts JSON `{"key": "..."}` on any POST path and prints it.
- `keylogger.js` is a userscript that buffers keystrokes and dumps input values on focus timeout, blur, and submit.

---

## Configuration

| Item | Location | Notes |
| --- | --- | --- |
| Preset sites | `novnc/app.py` `PRESET_SITES` | Add keys to extend `-l`. |
| Mobile sizes | `novnc/app.py` `MOBILE_SIZES` | Add keys to extend `-s`. |
| Default port | `novnc/app.py` `DEFAULT_PORT` | 80; change if the host port is busy. |
| Profile dir | `novnc/app.py` `FIREFOX_DATA_DIR` | `/docker/appdata/firefox`. |
| BitB window title/domain | `bitb/attacker_index.html` | Passed into `launchBitB(title, domain)`. |
| Fake URL path | `bitb/bitb_payload.js` | Cosmetic only; does not affect the iframe origin. |
| Keystroke endpoint | `novnc/keylogger.js` `LISTENER_URL` | Defaults to the Docker bridge gateway on port 3000. |
| Container names | `firefox-setup`, `firefox-kiosk` | Referenced by `docker cp` and teardown. |

Environment variables passed to the container:

| Variable | Mode | Purpose |
| --- | --- | --- |
| `FF_KIOSK=1` | desktop, mobile | Full-screen kiosk mode. |
| `FF_OPEN_URL` | desktop, mobile | Initial page loaded by kiosk Firefox. |
| `DISPLAY_WIDTH` | mobile | Virtual display width. |
| `DISPLAY_HEIGHT` | mobile | Virtual display height. |

---

## Cleanup

Stop and remove the containers:

```bash
python3 novnc/app.py stop -y
```

Stop, remove, and wipe the Firefox profile:

```bash
python3 novnc/app.py reset -y
```

If you used BitB mode, also restore the User-Agent file if you want a clean profile state:

```bash
rm -f /docker/appdata/firefox/user.js
```

`Ctrl+C` in `run.py` terminates the backend and attempts `app.py stop -y`. A Cloudflare Quick Tunnel is ephemeral and closes with the process.

---

## Limitations

- **Single session per instance.** All visitors share the same Firefox profile and VNC session. mr.d0x's multi-session approach is not implemented here.
- **No per-target isolation.** Cookies and history persist between visitors unless the profile is reset.
- **Cloudflare Quick Tunnel URLs are random and short-lived.** They are convenient for demos, not for stable infrastructure.
- **Port 80 default may require privileges.** Use `-p` to map an unprivileged host port.
- **Mobile emulation is cosmetic.** It changes viewport and User-Agent, not device fingerprint or rendering engine.
- **The BitB window is only as convincing as the template.** Differences in fonts, scaling, and OS window chrome can reveal it under scrutiny.
- **No anti-bot or filter evasion.** Modern browsers, EDR, and secure web gateways may flag or block the tunnel domain or the noVNC canvas.
- **The keystroke listener is unauthenticated and plaintext.** It is a lab tool, not a hardened collection service.
- **The `--script` option is declared but not wired into deployment.** Inject userscripts manually for now.

---

## Detection and mitigation

This section exists so defenders can recognize the technique.

- **Look beyond the rendered URL bar.** Open the real browser chrome, inspect the page source, or check the top-level origin. A login form rendered inside an iframe with a canvas is suspicious.
- **Detect noVNC/RFB traffic.** WebSocket upgrades with `Sec-WebSocket-Protocol: binary` to endpoints such as `/websockify`, plus large binary frames, are characteristic.
- **Fingerprint canvas-based remote desktops.** Cross-origin iframes backed by `<canvas>` without normal DOM form elements are a signal.
- **Block or log `trycloudflare.com` and other quick-tunnel domains.** Enterprise proxies should treat them as untrusted by default.
- **Enforce phishing-resistant MFA.** Passkeys/WebAuthn bound to the legitimate origin defeat relayed or remote-session credential capture, including this one.
- **Restrict browser popups and cross-origin iframes** where policy allows.
- **User awareness:** a padlock and a domain inside a page are not proof of origin. Teach users to open the site directly rather than through links.

---

## Legal and ethical notice

This software is provided for **educational purposes, security research, and authorized red-team engagements only**.

- Do not use it to access accounts, systems, or data you do not own or have written permission to test.
- Capturing credentials, session cookies, or keystrokes from people who have not consented is unlawful in most countries.
- The authors and contributors accept no liability for misuse or damage caused by this project.
- If you are unsure whether your use is authorized, stop and consult your legal team.

By using this repository you agree that you are responsible for complying with all applicable laws and regulations.

---

## Credits

- **mr.d0x** for the original research and public write-ups:
  - [Browser In The Browser (BITB) Attack](https://mrd0x.com/browser-in-the-browser-phishing-attack/)
  - [Steal Credentials & Bypass 2FA Using noVNC](https://mrd0x.com/bypass-2fa-using-novnc/)
  - BitB templates: [github.com/mrd0x/BITB](https://github.com/mrd0x/BITB)
- **noVNC** project: [novnc/noVNC](https://github.com/novnc/noVNC) and [novnc.com](https://novnc.com/info.html)
- **jlesage/firefox** container image: [jlesage/docker-firefox](https://github.com/jlesage/docker-firefox)
- **Cloudflare Quick Tunnel** via `cloudflared`: [Cloudflare docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)

TwinPhish is an independent proof-of-concept and is not affiliated with or endorsed by mr.d0x, noVNC, Jlesage, Google, Cloudflare, or any referenced vendor.

---

## References

1. mr.d0x, "Browser In The Browser (BITB) Attack", March 2022. <https://mrd0x.com/browser-in-the-browser-phishing-attack/>
2. mr.d0x, "Steal Credentials & Bypass 2FA Using noVNC", February 2022. <https://mrd0x.com/bypass-2fa-using-novnc/>
3. noVNC documentation. <https://novnc.com/info.html>
4. Cloudflare, "TryCloudflare". <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/>
5. fhlipZero, "noVNC phishing write-up". <https://fhlipzero.io/blogs/6_noVNC/noVNC.html>

---

## License

No license is granted for malicious use. Add a license of your choice (for example MIT or BSD-3-Clause) if you intend to redistribute this code for legitimate research or training. The disclaimer above takes precedence over any permissive terms.
