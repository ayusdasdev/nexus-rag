# Nexus Widgets

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
