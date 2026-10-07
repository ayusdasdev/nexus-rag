"""Generate sample documents for manually testing the ingestion pipeline.

    uv run python scripts/make_sample_docs.py

Writes into sample_docs/ at the project root. Output is deterministic: no
timestamps, no randomness. The content is original, about a fictional product
line called "Nexus Widgets".
"""

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_docs"

PAGE_W, PAGE_H = 612, 792
MARGIN = 72
TEXT_W = PAGE_W - 2 * MARGIN
FIXED_PDF_DATE = "D:20260101000000+00'00'"

PROSE = {
    "intro": (
        "Nexus Widgets are small battery-powered sensors that measure temperature, humidity and "
        "vibration in warehouses, kitchens and workshops. Each widget reports readings every "
        "thirty seconds over a low-power radio link to a hub, and the hub forwards the data to "
        "the Nexus cloud. This guide explains how to plan a deployment, install and calibrate "
        "the hardware, and read the dashboards."
    ),
    "planning": (
        "Before ordering hardware, map the spaces you want to monitor. Walk each room and note "
        "where the most reliable wall or ceiling mount would sit, how far it is from the nearest "
        "hub, and whether metal shelving will block the signal. A widget placed behind a steel "
        "rack typically needs a second hub, or a repeater, to keep a steady link. Record the "
        "floor plan with rough distances, because the planning tool in the dashboard asks for "
        "them later."
    ),
    "install_1": (
        "Mount each widget with the adhesive pad or the screw bracket included in the box. The "
        "adhesive pad works well on smooth painted surfaces, but it should not be used on "
        "textured plaster or on surfaces that will see temperatures above fifty degrees Celsius. "
        "The screw bracket is the better choice for those places. Keep the sensor face unobstructed "
        "so that the air around it moves freely, because a widget boxed in behind a panel reports "
        "temperatures that run several degrees high."
    ),
    "install_2": (
        "Power the hub from the included adapter and connect it to the building network with the "
        "Ethernet cable. The status light on the hub turns solid green once it has an address and "
        "a link to the cloud. A slow blue blink means the hub is waiting for the first widget to "
        "join. Pair widgets one at a time by holding the pairing button for three seconds until "
        "the widget light flashes white, then bring the widget within one metre of the hub. The "
        "pairing completes within about ten seconds, and the widget appears in the device list "
        "with its serial number."
    ),
    "calibration": (
        "Calibration corrects small offsets that come from manufacturing tolerances and from the "
        "mounting position. Place a reference thermometer beside a widget and let both settle for "
        "fifteen minutes. In the dashboard, open the device page, choose Calibrate, and enter the "
        "reference reading. The widget stores the offset and applies it to every later reading. "
        "Humidity calibration uses a saturated salt solution in the same way, and the procedure "
        "takes about an hour because the sensor needs time to reach equilibrium. Calibrate every "
        "widget once after installation and again after any change of mounting position."
    ),
    "alerts_1": (
        "Alerts are rules that compare a reading with a threshold for a set duration. A rule "
        "named cold storage high, for example, can fire when the temperature stays above four "
        "degrees for ten minutes. Rules can be scoped to a single widget, to a group of widgets, "
        "or to a whole site. When a rule fires, the dashboard shows the alert in the feed, and "
        "the configured channels receive a notification. Each channel can be an email address, a "
        "chat webhook or a text message, and every rule can use several channels at once."
    ),
    "alerts_2": (
        "Avoid very short durations. A duration of thirty seconds will fire on a door opening "
        "and closing, which produces noise without helping anyone. Most teams find that five to "
        "fifteen minutes gives a good balance between early warning and quiet nights. Snoozing an "
        "alert silences its notifications for a chosen period but keeps the event in the feed, so "
        "the history stays complete for later review and for audit purposes."
    ),
    "calibration_more": (
        "After calibration, check the result on a second reference point. Warm the widget by "
        "holding it in a closed hand for two minutes, then compare the reading with a thermometer "
        "in a bag beside it. The difference should be under half a degree. If it is larger, repeat "
        "the procedure with a fresh reference reading, because a reference that was still warming "
        "up is the most common cause of a poor offset. Note the date, the reference used and the "
        "final offset in the device logbook so that the history of each widget can be reviewed."
    ),
    "calibration_drift": (
        "Sensors drift slowly over several years. A widget that was accurate when installed may read "
        "half a degree high after three years, which is inside the stated tolerance but can still "
        "matter for cold chain records. Schedule a check every twelve months for devices that hold "
        "regulated stock, and recalibrate any widget that falls outside the tolerance printed on its "
        "label. Devices that are replaced should be calibrated before they join the hub, so that the "
        "new serial number starts with a valid offset."
    ),
    "network": (
        "The hub needs an address from the building network, either by DHCP or a fixed address. It "
        "connects outward to the Nexus cloud over HTTPS on port 443, and it does not need any inbound "
        "port to be opened. If your firewall inspects traffic, allow the hostname printed on the hub "
        "label and disable content rewriting for that host. The hub checks the time against a network "
        "time server on start-up, so an outbound route for NTP is also useful. Readings are buffered "
        "on the hub for up to six hours if the cloud link drops, and they are sent in order once the "
        "link returns."
    ),
    "maintenance": (
        "Routine maintenance takes less than an hour per site. Every quarter, wipe the sensor faces "
        "with a dry cloth to remove dust, which can slow the response of the humidity sensor. Check "
        "the battery indicator on each widget and replace any battery that has fallen below twenty "
        "percent, using only the cell type listed on the label. Apply the latest firmware from the "
        "dashboard, and confirm on the hub page that every widget reports the same firmware version. "
        "Keep a short written record of the visit so that the maintenance history is visible to the "
        "whole team."
    ),
    "retention": (
        "Readings are kept for ninety days at full resolution and for two years as hourly averages. "
        "Alert events are kept for one year. Administrators can export any of these ranges as CSV or "
        "as a JSON file, and exports are available for thirty days after they are created. Deleting a "
        "device removes its readings from the dashboard immediately, and the deletion is completed in "
        "the backups within thirty days. Account owners can request a full deletion of an account, and "
        "that request is confirmed by email before it is carried out."
    ),
    "roles": (
        "Access is controlled by three roles. Viewers can see devices, readings and alerts but cannot "
        "change anything. Operators can add and remove widgets, acknowledge alerts and run calibrations. "
        "Administrators also manage members, alert channels and the account plan. Assign the smallest "
        "role that a person needs, and review the member list every quarter, because people change "
        "teams and their access should change with them."
    ),
    "glossary_1": (
        "Widget. A battery-powered sensor that measures temperature and humidity and, on some models, "
        "vibration. Each widget has a serial number printed on its label and a unique identifier in the "
        "dashboard. Widgets never talk to the cloud directly; they always report through a hub."
    ),
    "glossary_2": (
        "Hub. The gateway that joins widgets to the building network and forwards their readings to "
        "the cloud. A hub buffers readings during outages, keeps the widget list, and applies firmware "
        "updates. Each site needs at least one hub, and large sites may need more than one."
    ),
    "glossary_3": (
        "Calibration offset. A correction value stored on a widget and applied to every reading it "
        "produces. Offsets are measured against a reference instrument and remain in place until the "
        "widget is calibrated again or removed from the device list."
    ),
    "faq_1": (
        "Can widgets share a hub with other radio equipment? Yes, as long as the other equipment does "
        "not use the same channel for long periods. The hub chooses a quiet channel at start-up and "
        "moves to another one if interference is detected, which takes about a minute and does not lose "
        "any buffered readings."
    ),
    "faq_2": (
        "What happens when the battery of a widget is replaced? The widget keeps its serial number, its "
        "calibration offset and its alert rules. Readings resume within one reporting interval once the "
        "new battery is seated and the status light has flashed white twice."
    ),
    "faq_3": (
        "Is there a way to test an alert without waiting for a real event? Yes. Each rule has a Test "
        "button that sends a sample notification through the channels attached to that rule. The test "
        "notification is marked clearly as a test and does not appear in the event history."
    ),
    "api": (
        "The Nexus API exposes devices, readings and alerts over HTTPS with JSON bodies. Requests "
        "are authenticated with a bearer token that you create in the account settings. Readings "
        "are paginated by timestamp, and the largest page size is one thousand rows. Rate limits "
        "are generous for dashboards and integrations, but bulk exports should use the export "
        "endpoint, which returns a file that can be downloaded once it is ready."
    ),
    "troubleshoot": (
        "If a widget stops reporting, first check the battery indicator on the device page. Below "
        "ten percent the widget reduces its transmission rate to conserve power, which looks like "
        "a gap in the chart. Next, check the distance to the hub and whether a new metal object "
        "has been placed between them. A widget that has been powered off and on again rejoins "
        "the hub automatically, and the gap closes within one reporting interval."
    ),
}

PLANS = [
    ("Plan", "Monthly price", "Widgets included", "Support"),
    ("Starter", "19 USD", "5", "Email, 2 business days"),
    ("Team", "79 USD", "25", "Email and chat, 1 business day"),
    ("Growth", "249 USD", "100", "Priority chat, 4 hours"),
    ("Enterprise", "Custom", "Unlimited", "Dedicated engineer, 1 hour"),
]


def _fixed_metadata(doc: pymupdf.Document, title: str) -> None:
    doc.set_metadata(
        {
            "title": title,
            "author": "Nexus Widgets documentation team",
            "creationDate": FIXED_PDF_DATE,
            "modDate": FIXED_PDF_DATE,
            "producer": "scripts/make_sample_docs.py",
            "creator": "scripts/make_sample_docs.py",
        }
    )


def _save(doc: pymupdf.Document, path: Path) -> None:
    doc.save(path, deflate=True, garbage=4, no_new_id=True)
    doc.close()


class _Flow:
    """Writes blocks top to bottom, starting a new page when a block does not fit."""

    def __init__(
        self, doc: pymupdf.Document, column: tuple[float, float] | None = None
    ) -> None:
        self.doc = doc
        self.page = doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN + 30
        self.column = column or (MARGIN, MARGIN + TEXT_W)

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN

    def block(self, text: str, size: float, bold: bool = False, gap: float = 8) -> None:
        font = "hebo" if bold else "helv"
        left, right = self.column
        while True:
            rect = pymupdf.Rect(left, self.y, right, PAGE_H - MARGIN)
            remaining = self.page.insert_textbox(
                rect, text, fontsize=size, fontname=font, lineheight=1.25
            )
            if remaining >= 0:
                self.y += (PAGE_H - MARGIN - self.y) - remaining + gap
                return
            self._new_page()

    def title(self, text: str) -> None:
        self.block(text, 22, bold=True, gap=14)

    def h1(self, text: str) -> None:
        self.block(text, 16, bold=True, gap=8)

    def h2(self, text: str) -> None:
        self.block(text, 13, bold=True, gap=6)

    def para(self, text: str) -> None:
        self.block(text, 10.5, gap=8)


def make_text_heavy(path: Path) -> None:
    doc = pymupdf.open()
    _fixed_metadata(doc, "Nexus Widgets Deployment Guide")
    flow = _Flow(doc)
    flow.title("Nexus Widgets Deployment Guide")
    flow.h1("1. Introduction")
    flow.para(PROSE["intro"])
    flow.h1("2. Planning your deployment")
    flow.para(PROSE["planning"])
    flow.h1("3. Installing hardware")
    flow.h2("3.1 Mounting widgets")
    flow.para(PROSE["install_1"])
    flow.h2("3.2 Setting up the hub")
    flow.para(PROSE["install_2"])
    flow.h1("4. Calibration")
    flow.para(PROSE["calibration"])
    flow.para(PROSE["calibration_more"])
    flow.para(PROSE["calibration_drift"])
    flow.h1("5. Alerts")
    flow.h2("5.1 Writing rules")
    flow.para(PROSE["alerts_1"])
    flow.h2("5.2 Choosing durations")
    flow.para(PROSE["alerts_2"])
    flow.h1("6. Network and security")
    flow.para(PROSE["network"])
    flow.h1("7. Maintenance")
    flow.para(PROSE["maintenance"])
    flow.h1("8. Data retention")
    flow.para(PROSE["retention"])
    flow.h1("9. Roles and access")
    flow.para(PROSE["roles"])
    flow.h1("10. Glossary")
    flow.para(PROSE["glossary_1"])
    flow.para(PROSE["glossary_2"])
    flow.para(PROSE["glossary_3"])
    flow.h1("11. Frequently asked questions")
    flow.para(PROSE["faq_1"])
    flow.para(PROSE["faq_2"])
    flow.para(PROSE["faq_3"])
    flow.h1("12. API and troubleshooting")
    flow.para(PROSE["api"])
    flow.para(PROSE["troubleshoot"])
    _save(doc, path)


def make_table(path: Path) -> None:
    doc = pymupdf.open()
    _fixed_metadata(doc, "Nexus Widgets Pricing and Specifications")
    flow = _Flow(doc)
    flow.title("Pricing and specifications")
    flow.para(
        "The table below lists the four plans. Prices are per month and billed annually. "
        "Widget limits apply per account."
    )
    page = flow.page
    col_x = [MARGIN, MARGIN + 90, MARGIN + 190, MARGIN + 300, MARGIN + TEXT_W]
    row_h = 26
    top = flow.y + 10
    for r, row in enumerate(PLANS):
        y0 = top + r * row_h
        for c, cell in enumerate(row):
            page.insert_text(
                (col_x[c] + 6, y0 + 17),
                cell,
                fontsize=10,
                fontname="hebo" if r == 0 else "helv",
            )
    for x in col_x:
        page.draw_line((x, top), (x, top + len(PLANS) * row_h))
    for r in range(len(PLANS) + 1):
        y = top + r * row_h
        page.draw_line((col_x[0], y), (col_x[-1], y))
    flow.y = top + len(PLANS) * row_h + 20
    flow.para(
        "Every plan includes the mobile dashboard, unlimited readings history for ninety days, and "
        "the standard alert channels. The Growth and Enterprise plans add the export endpoint and "
        "single sign-on. Overage widgets are billed at the rate of the plan in use."
    )
    _save(doc, path)


def make_two_column(path: Path) -> None:
    doc = pymupdf.open()
    _fixed_metadata(doc, "Nexus Widgets Two-Column Notes")
    left = [
        f"LEFT-{i:02d} " + sentence
        for i, sentence in enumerate(
            [
                "Widgets report every thirty seconds when they have a clear link to the hub.",
                "A hub supports up to fifty widgets on a single radio channel.",
                "Place the hub at a central height, away from metal cabinets and microwave ovens.",
                "The status light shows whether the hub is connected to the cloud.",
                "Pairing requires holding the widget button for three seconds.",
                "Battery life is about two years at the default reporting interval.",
                "Lowering the reporting interval shortens battery life accordingly.",
                "Firmware updates install overnight when the hub is idle.",
                "Each widget keeps its own calibration offset after a restart.",
                "Remove a widget from the device list before reusing its serial number.",
                "The export endpoint returns CSV files for offline analysis.",
                "Support can read the diagnostic log from the device page on request.",
            ],
            start=1,
        )
    ]
    right = [
        f"RIGHT-{i:02d} " + sentence
        for i, sentence in enumerate(
            [
                "Alerts can be scoped to one widget, a group of widgets, or a whole site.",
                "Every rule chooses how long a condition must hold before it fires.",
                "Snoozing silences notifications but keeps the event in the feed.",
                "Channels include email, chat webhooks and text messages.",
                "Dashboards refresh every fifteen seconds while the page is open.",
                "Charts can show up to ninety days of history at full resolution.",
                "Exported charts include the calibration offset that was applied.",
                "Teams can share saved views with read-only access.",
                "Administrators control which members can create alert rules.",
                "Audit events record who changed a rule and when.",
                "The mobile app shows the same feed as the web dashboard.",
                "Offline mode queues acknowledgements until the connection returns.",
            ],
            start=1,
        )
    ]
    filler = (
        "Continuation notes. This page carries general reminders about storage and labelling. "
        "Keep spare widgets in a dry drawer at room temperature, and label each one with the site "
        "name before it leaves the office. Batteries should be replaced only by trained staff."
    )

    gutter = 18
    col_w = (TEXT_W - gutter) / 2
    columns = [(MARGIN, MARGIN + col_w), (MARGIN + col_w + gutter, MARGIN + TEXT_W)]

    pages = [(left, right), ([filler], [filler]), ([filler], [filler])]
    for page_no, (left_items, right_items) in enumerate(pages, start=1):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_textbox(
            pymupdf.Rect(MARGIN, 36, PAGE_W - MARGIN, 56),
            "NEXUS-RUNNING-HEADER",
            fontsize=9,
            fontname="hebo",
        )
        for col, items in zip(columns, [left_items, right_items]):
            body = "\n\n".join(items)
            page.insert_textbox(
                pymupdf.Rect(col[0], 90, col[1], PAGE_H - 90),
                body,
                fontsize=10,
                fontname="helv",
                lineheight=1.3,
            )
        page.insert_textbox(
            pymupdf.Rect(MARGIN, PAGE_H - 50, PAGE_W - MARGIN, PAGE_H - 30),
            f"NEXUS-CONFIDENTIAL-FOOTER Page {page_no} of {len(pages)}",
            fontsize=9,
            fontname="helv",
        )
    _save(doc, path)


def make_scanned(path: Path) -> None:
    source = pymupdf.open()
    page = source.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_textbox(
        pymupdf.Rect(MARGIN, MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN),
        "Scanned intake form. Name, serial number, site, date of installation.",
        fontsize=16,
    )
    pixmap = page.get_pixmap(dpi=100, colorspace=pymupdf.csGRAY)
    source.close()
    doc = pymupdf.open()
    _fixed_metadata(doc, "Scanned intake form")
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_image(page.rect, stream=pixmap.tobytes("jpg", jpg_quality=60))
    _save(doc, path)


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Calibrating widgets - Nexus Docs</title>
</head>
<body>
  <div class="cookie-banner" role="dialog">
    <p>We use cookies to improve the docs. ACCEPT-ALL-COOKIES</p>
  </div>
  <nav class="top-nav">
    <ul>
      <li class="nav-item"><a href="/">NAV-MENU-ITEM Home</a></li>
      <li class="nav-item"><a href="/guides">NAV-MENU-ITEM Guides</a></li>
      <li class="nav-item"><a href="/api">NAV-MENU-ITEM API</a></li>
      <li class="nav-item"><a href="/changelog">NAV-MENU-ITEM Changelog</a></li>
    </ul>
  </nav>
  <div class="layout">
    <aside class="sidebar">
      <h4>In this guide</h4>
      <ul>
        <li><a href="#offsets">Offsets</a></li>
        <li><a href="#humidity">Humidity</a></li>
        <li><a href="#troubleshooting">Troubleshooting</a></li>
      </ul>
    </aside>
    <main>
      <article>
        <h1>Calibrating widgets</h1>
        <p>Calibration corrects small offsets that come from manufacturing tolerances and from the
        mounting position. A widget that is calibrated once keeps its offset across restarts.</p>
        <h2 id="offsets">Temperature offsets</h2>
        <p>Place a reference thermometer beside the widget and wait fifteen minutes. Then enter the
        reference reading on the device page.</p>
        <h3>Using the calibration command</h3>
        <p>The same step can be run from the command line:</p>
        <pre><code>nexus-cli devices calibrate --device WID-0042 --reference 21.5

nexus-cli devices show --device WID-0042</code></pre>
        <h2 id="humidity">Humidity offsets</h2>
        <p>Humidity calibration uses a saturated salt solution. The steps are:</p>
        <ul>
          <li>Seal the widget and the reference in a container for one hour.</li>
          <li>Record the reference humidity from the label on the solution.</li>
          <li>Enter the value on the device page.</li>
        </ul>
        <h2 id="troubleshooting">Troubleshooting</h2>
        <h3>Offset looks wrong after moving a widget</h3>
        <p>Calibrate again after any change of mounting position. Offsets do not follow a widget
        between sites.</p>
      </article>
    </main>
  </div>
  <footer>
    <p>Nexus Widgets documentation. FOOTER-LINKS <a href="/privacy">Privacy</a> <a href="/terms">Terms</a> <a href="/status">Status</a></p>
  </footer>
</body>
</html>
"""

README_MD = """# Nexus Widgets

Nexus Widgets are battery-powered sensors that report readings to a hub and then to the cloud.

## Getting started

Install the desktop tools and create an account before you pair your first widget.

### Requirements

- A hub with firmware 4.2 or later
- A browser that supports HTTPS
- A network port reachable from the hub

### First run

Run the setup wizard from the dashboard. It checks the network and walks you through pairing.

## Command line

The CLI reads the same account as the dashboard.

```bash
nexus login --account acme
nexus devices list

# Export the last day of readings as CSV.
nexus readings export --since 1d --format csv
```

## Plans

| Plan | Price | Widgets |
|------|-------|---------|
| Starter | 19 USD | 5 |
| Team | 79 USD | 25 |
| Growth | 249 USD | 100 |

## License

Internal sample document for manual testing.
"""


def make_html(path: Path) -> None:
    path.write_text(HTML_PAGE, encoding="utf-8")


def make_readme(path: Path) -> None:
    path.write_text(README_MD, encoding="utf-8")


GENERATORS = {
    "01_text_heavy.pdf": make_text_heavy,
    "02_table.pdf": make_table,
    "03_two_column.pdf": make_two_column,
    "04_docs_page.html": make_html,
    "05_README.md": make_readme,
    "06_scanned.pdf": make_scanned,
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, generate in GENERATORS.items():
        generate(OUT / name)
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
