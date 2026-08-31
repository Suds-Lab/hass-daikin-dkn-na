# Changelog

All notable changes to this project are documented in this file. This project
adheres to [Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-08-31

### Security
- The account refresh token is no longer written to logs or surfaced in the UI.
  A failed token refresh previously interpolated the full token (embedded in the
  request route) into the exception message, which Home Assistant logged and
  displayed. The route is now redacted (`auth/refreshToken/<redacted>/dknUsa`).

### Fixed
- The socket connection now recovers on its own instead of needing a manual
  "Reload" when devices stop responding: keepalive pings survive a token
  refresh, a single malformed packet or a raising callback can no longer kill
  the poll loop, and a new watchdog forces a reconnect when the connection goes
  silent or the installation namespace drops. Added debug logging around these
  paths.
- The vendored client's `__version__` now matches the manifest (was `0.1.0`).

### Removed
- The redundant root `brands/` directory. Home Assistant 2026.3+ reads local
  brand images from the in-tree `custom_components/dkn_cloud_na/brand/` folder.

## [0.1.1] - 2026-06-09

### Changed
- Brand icon now uses a transparent background (renders correctly on light and
  dark themes via the local `brand/` assets).

## [0.1.0] - 2026-06-09

Initial release.

### Added
- **Climate entity** per unit: power, HVAC mode (auto / cool / heat / fan / dry),
  current and target temperature, fan speed, and louvre **swing** - vertical and/or
  horizontal depending on what each unit reports.
- **Diagnostic sensors**: outdoor temperature, Wi-Fi signal, outdoor-unit current,
  and air quality (PM1 / PM2.5 / PM10) - added only when the hardware reports them.
- **Binary sensors**: connectivity, problem, and temperature-sensor problem.
- **Live, cloud-push updates** over the DKN Cloud NA service (no polling).
- **UI configuration**: sign in with your DKN Cloud NA account; all installations
  and units are discovered automatically.
- **°F / °C** following each unit's own temperature setting.

[0.1.2]: https://github.com/Suds-Lab/hass-daikin-dkn-na/releases/tag/v0.1.2
[0.1.1]: https://github.com/Suds-Lab/hass-daikin-dkn-na/releases/tag/v0.1.1
[0.1.0]: https://github.com/Suds-Lab/hass-daikin-dkn-na/releases/tag/v0.1.0
