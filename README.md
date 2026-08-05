# Instagram Mobile Bloks Signup

Terminal lab that creates Instagram accounts through the **mobile web Bloks / CAA** flow (`/async/wbloks/fetch`) — not desktop GraphQL.

Paste proxies, plug any email inbox API, run concurrent bots. Successful accounts land in `hits.csv`.

![Demo: one bot completing signup](docs/demo-terminal.png)

---

## Why this exists

Most IG signup scripts target the wrong surface (old GraphQL / desktop CAA). This one follows the **mobile Safari Bloks** path used by Instagram’s mobile web registration, with:

- Pluggable email APIs (you wire your own provider in ~3 functions)
- Sticky proxy `<SID>` replacement per bot
- Parallel workers and CSV hit export

**Problem it solves:** experiment with / automate mobile Bloks signup without rebuilding HTTP, Bloks parsing, and email polling from scratch.

---

### Disclaimer

This flow expects **high-quality mobile proxies** and **high-trust email domains**.
Cheap datacenter / low-reputation lines and throwaway domains usually fail early
(blocks, no code, create errors). Sticky IPs help, but they won’t save bad proxy
or email quality.

Educational / research use. You own your accounts, keys, and proxies.

---

## Installation

```bash
git clone https://github.com/r0xptth/Instagram-Bloks-Signup.git
cd Instagram-Bloks-Signup
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env                 # or: cp .env.example .env
copy proxies.txt.example proxies.txt
```

Then:

1. Copy `email_plugins/_example.py` → `email_plugins/my_mail.py` and wire your email API
2. Put your API key in `.env`
3. Paste proxy lines into `proxies.txt` (use `<SID>` for sticky sessions)

---

## Quick start

```bash
python run.py --list-emails
python run.py --email my_mail --bots 1
python run.py --email my_mail --bots 5
```

Start with `--bots 1` until you get a hit, then scale.

---

## Example output

**Terminal**

```text
[21:04:11] INFO email=my_mail balance=12.5
[21:04:11] INFO start · bots=1 · proxies=3 · email=my_mail · hits=hits.csv
[21:04:12] INFO [bot-1] starting via gate.example.com:10001
[21:04:18] INFO [my_mail] ordered demo.user@outlook.com (id 8f3a21)
[21:04:41] INFO [my_mail] code received
[21:05:06] INFO [bot-1] HIT @maya.rivera.04 · demo.user@outlook.com
[21:05:06] INFO done · 1/1 hit(s) → hits.csv
```

**`hits.csv`**

```csv
Username,Password,Email,Session ID,Proxy Provider,Proxy
maya.rivera.04,Tr0pical!wave9,demo.user@outlook.com,1234567890%3A...,,gate.example.com:10001:user-...:pass
```

---

## Proxies

One line per proxy in `proxies.txt`:

| Format | Example |
|--------|---------|
| `user:pass@host:port` | `user:pass@gate.example.com:7777` |
| `host:port:user:pass` | `gate.example.com:7777:user:pass` |
| `user:pass:host:port` | `user:pass:gate.example.com:7777` |
| `http://user:pass@host:port` | `http://user:pass@gate.example.com:7777` |
| `host:port` | `1.2.3.4:8080` |

### Sticky sessions (`<SID>`)

Signup needs the same IP for the whole flow. Rotating mid-run usually kills the bot.

If your provider uses a session id in the username or password, leave `<SID>` in
`proxies.txt`. At runtime the lab swaps it for a unique id per bot.

```text
user-XXXX-country-us-session-<SID>-sessionduration-30:PASSWORD@gate.example.com:10001
```

Bot 1 might become `session-b100123`, bot 2 `session-b200456`, etc.

No `<SID>` in your line? Nothing is rewritten; the proxy is used as-is.

Prefer HQ mobile proxies over cheap datacenter. Pair them with high-trust email domains.

---

## Email plugins

No builtins — wire your own inbox API.

```bash
copy email_plugins\_example.py email_plugins\my_mail.py
```

Fill in three functions in `my_mail.py`:

| Function | Job |
|----------|-----|
| `create_order` | buy/rent an inbox → return order id + email |
| `get_code` | check once for the IG code (or say still waiting) |
| `cancel_order` | cancel / refund |

`email_plugins/_example.py` has the full return shapes and helpers.
Put your key in `.env`, then:

```bash
python run.py --email my_mail --bots 1
```

(`--email` is the filename stem: `my_mail.py` → `my_mail`)

---

## Project layout

```
Instagram-Bloks-Signup/
  run.py                 # CLI entry
  email_api.py           # helpers for custom plugins
  docs/demo-terminal.png # README demo screenshot
  .env                   # API keys (gitignored)
  proxies.txt            # your proxies (gitignored)
  hits.csv               # created on first hit (gitignored)
  bloks/                 # mobile Bloks signup client
  email_plugins/
    _example.py          # copy → my_mail.py
    my_mail.py           # your custom plugin
```

---

## Notes

- Mobile Safari CAA Bloks flow — not desktop GraphQL CAA.
- HQ mobile proxies + high-trust email domains matter more than bot count.
- Bad sticky / rotating IP mid-signup is a common silent killer.
- PRs and issues welcome; releases will track usable milestones.

Built for experiments. Break it, measure it, plug your own email API in.
