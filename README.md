<p align="center">
  <img src="custom_components/dkn_cloud_na/brand/logo.png" alt="DKN Cloud NA" width="520">
</p>

<p align="center">
  <a href="https://github.com/Suds-Lab/hass-daikin-dkn-na/actions/workflows/validate.yml">
    <img src="https://github.com/Suds-Lab/hass-daikin-dkn-na/actions/workflows/validate.yml/badge.svg" alt="Validate">
  </a>
  <a href="https://hacs.xyz">
    <img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom">
  </a>
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT">
</p>

Control your **Daikin / Airzone "DKN Cloud NA"** air-conditioning units from
[Home Assistant](https://www.home-assistant.io/). Each unit becomes a full
climate entity - power, mode, target temperature and fan speed - with live
status updates.

This integration works with the units managed by the **DKN Cloud NA** mobile
app (the **ES.DKNWSERVER** Wi-Fi adapter, sold for Daikin systems in North
America). It connects to the same cloud service the app uses, so it works with
DKN Cloud NA accounts that other Daikin/Airzone integrations don't support.

## Features

- 🌡️ **Climate entity per unit** - on/off, HVAC mode (auto, cool, heat, fan, dry),
  current temperature, target temperature, fan speed, and louvre swing (where the
  unit supports it).
- 📊 **Diagnostic sensors** - outdoor temperature, Wi-Fi signal, outdoor-unit
  current draw and air quality (PM1 / PM2.5 / PM10), shown only when the hardware
  reports them.
- 🚦 **Status sensors** - connectivity and fault/problem binary sensors per unit.
- ⚡ **Live updates** - state is pushed in real time; the integration does not
  poll, so it stays responsive without hammering the service.
- 🏢 **Multiple homes/zones** - every installation and unit on your account is
  added automatically.
- 🌎 **°F or °C** - follows each unit's own temperature setting.

## Requirements

- A **DKN Cloud NA** account (the same email and password you use in the app),
  with your units already set up and online in the app.
- Home Assistant 2024.12 or newer.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Suds-Lab&repository=hass-daikin-dkn-na&category=integration)

Click the button above (requires [HACS](https://hacs.xyz)) to add this repository
to HACS in one step, then **Download** it and **restart** Home Assistant.

Or add it manually:

1. In Home Assistant, open **HACS**.
2. Click the **⋮** menu (top-right) → **Custom repositories**.
3. Add the repository URL `https://github.com/Suds-Lab/hass-daikin-dkn-na`
   and choose the category **Integration**, then **Add**.
4. Search for **DKN Cloud NA** and click **Download**.
5. **Restart** Home Assistant.

### Manual

1. Copy the `custom_components/dkn_cloud_na` folder from this repository into
   your Home Assistant `config/custom_components/` directory.
2. **Restart** Home Assistant.

## Setup

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **DKN Cloud NA**.
3. Sign in with your DKN Cloud NA **email** and **password**.

Your installations and units are discovered automatically and appear as
`climate` entities, ready to use on dashboards, in automations and with voice
assistants.

## Notes & limitations

- This is a **cloud** integration: it requires an internet connection and a
  working DKN Cloud NA account. There is no local-only control for the stock
  ES.DKNWSERVER adapter.
- A unit shows as *unavailable* in Home Assistant whenever it is offline or
  unreachable in the DKN Cloud NA app.

## Troubleshooting

- **"Invalid authentication"** - double-check the email/password by signing in
  with the DKN Cloud NA app; the integration uses the same credentials.
- **No units appear** - make sure the units are online in the app first, then
  reload the integration from **Settings → Devices & Services**.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Disclaimer

This is an unofficial, community-built integration. It is not affiliated with,
endorsed by, or supported by Daikin or Airzone. "DKN Cloud NA", "Daikin" and
"Airzone" are trademarks of their respective owners. Use it with equipment you
own.

## License

Released under the [MIT License](LICENSE).
