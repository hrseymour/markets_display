# Markets Display

A wall-mounted market dashboard for Raspberry Pi (Python 3.13, PyQt6).

Three live charts across the top of the screen and a grid of price tiles
along the bottom. The displayed market region rotates automatically by
time of day:

| Time (Pacific) | Region        | Default charts                |
| -------------- | ------------- | ----------------------------- |
| 06:30 – 17:00  | North America | DJI · S&P 500 · Nasdaq        |
| 17:00 – 00:00  | Asia          | Nikkei · Hang Seng · Shanghai |
| 00:00 – 06:30  | Europe        | FTSE · DAX · CAC              |

Everything that's worth tuning lives in [`config/config.yaml`](config/config.yaml):
colors, layout proportions, refresh cadence, region schedule, the
instruments shown in each region, and the provider order.

## What it looks like

Each chart has a CNBC-style banner at the top (large index name, current
price, signed change, percent change in brackets — colored green/red),
followed by a clean line chart with a dashed amber line marking the
previous session's close. The line itself is green or red based on the
day's net direction.

Each bottom tile is the same banner without the chart.

## Architecture

```
src/
├── __main__.py           # entry point
├── config.py             # YAML + .env loader
├── main_window.py        # top-level Qt window, region switching
├── data_service.py       # background fetcher (QThread)
├── scheduler.py          # time-of-day region picker
├── theme.py              # color theme from YAML
├── widgets/
│   ├── banner.py         # CNBC-style banner (used by chart and tile)
│   ├── chart.py          # simple line chart with prev-close line
│   └── chart_panel.py    # banner + chart composite
└── providers/
    ├── base.py           # DataProvider abstract class
    ├── yfinance_provider.py
    ├── eodhd_provider.py
    └── __init__.py       # dispatcher
```

The data layer is provider-agnostic. Each instrument in YAML declares its
ticker per provider, e.g.:

```yaml
- name: "DOW INDUSTRIALS"
  symbols:
    yfinance: "^DJI"
    eodhd:    "DJI.INDX"
```

The dispatcher walks `providers.order` in YAML, asks each one for the
data using its specific ticker, and falls through if a provider returns
`None` or errors.

## Adding a new data provider

1. Create `markets_display/providers/<vendor>_provider.py` subclassing
   `DataProvider`. Implement `get_quote()` and `get_intraday()`.
2. Register the class in `markets_display/providers/__init__.py`
   (`PROVIDER_CLASSES`).
3. Add a `<vendor>:` block under `providers:` in `config.yaml` and put
   it in the `providers.order` list.
4. Add `<vendor>: "TICKER"` under each instrument's `symbols:` block in
   YAML for the instruments that vendor should serve.

API keys go in `.env`, not YAML.

## Installation

### Raspberry Pi (Bookworm) or Ubuntu

```bash
git clone <your-repo-url> markets_display
cd markets_display
bash scripts/setup_pi.sh
```

This installs system packages PyQt6 needs, creates a virtualenv at
`.venv/`, installs Python deps, and copies `.env.example` → `.env`.

Edit `.env` and put your EODHD API key in `EODHD_API_KEY=`.

### Quick test (windowed, on the desktop)

```bash
source .venv/bin/activate
python -m markets_display --windowed
```

You should see a 3-chart-on-top, tiles-on-bottom dashboard. It will fetch
live data immediately and refresh every 60 seconds.

### Run fullscreen on the wall monitor

The included systemd unit launches the app on boot once the desktop is
up:

```bash
sudo cp scripts/markets_display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now markets_display
```

Logs go to `logs/markets_display.log` (rotated) and to systemd's journal:

```bash
journalctl -u markets_display -f
```

## Configuration cookbook

**Change which symbols are shown.** Edit the lists under `charts:` or
`tiles:` in `config/config.yaml`. The names are free text. The tickers
must match what each provider expects.

**Change colors.** Edit the `colors:` block. Standard hex; an alpha byte
(`#00D96433` for ~20% opacity) works for the area fill.

**Change the time windows.** Edit `schedule.windows`. Times are 24-hour
HH:MM in the timezone given by `schedule.timezone`.

**Force a specific provider for one instrument.** Add `provider: eodhd`
(or whatever) to that instrument in YAML.

**Run on a different size monitor.** Leave `display.resolution: auto`
and the layout scales. Fonts and paddings are relative to screen height,
so 1080p and 4K look proportionate.

**Disable fullscreen / show cursor.** Set `display.fullscreen: false`
and `display.hide_cursor: false`, or pass `--windowed`.

## Keyboard shortcuts

| Key   | Action               |
| ----- | -------------------- |
| `Esc` | Quit                 |
| `F11` | Toggle fullscreen    |
| `R`   | Force a data refresh |

## Notes on real-time data

`yfinance` is ~15-minute delayed for most major US indices, which is
fine for a wall display. EODHD's "All World" subscription is end-of-day;
intraday charts require their Intraday add-on.

When you want true real-time, add a Polygon / Finnhub / IEX / IBKR
provider following the "Adding a new data provider" steps above and
move it to the top of `providers.order`. The rest of the app doesn't
change.

## Troubleshooting

**Black screen on the Pi:** PyQt6 needs an X session. Make sure you're
running the desktop, not a console-only image. The systemd unit waits
for `graphical.target`.

**`qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`:** Install
the system packages:
`sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1`.

**Charts say "Loading…" forever:** Check `logs/markets_display.log`.
Most often it's network (the Pi can't reach yahoo or eodhd) or a wrong
ticker. yfinance is silent on bad tickers — try `^DJI` works,
`DJI` doesn't.

**Tiles show "—":** Same fix — bad ticker for that provider, or no
provider in `providers.order` has that ticker.
