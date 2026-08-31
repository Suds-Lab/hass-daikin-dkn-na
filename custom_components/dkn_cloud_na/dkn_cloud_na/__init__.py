"""dkn_cloud_na - async client for the Daikin DKN Cloud NA (dkncloudna.com) API."""

from __future__ import annotations

from .client import DknCloudNaClient
from .const import (
    MODE_AUTO,
    MODE_COOL,
    MODE_DRY,
    MODE_FAN,
    MODE_HEAT,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)
from .exceptions import (
    DknApiError,
    DknAuthError,
    DknConnectionError,
    DknError,
)
from .models import Device, Installation, parse_installations, sanitize_device
from .socket import DknSocket

__version__ = "0.1.2"

__all__ = [
    "DknCloudNaClient",
    "DknSocket",
    "Device",
    "Installation",
    "parse_installations",
    "sanitize_device",
    "DknError",
    "DknAuthError",
    "DknApiError",
    "DknConnectionError",
    "MODE_AUTO",
    "MODE_COOL",
    "MODE_HEAT",
    "MODE_FAN",
    "MODE_DRY",
    "UNIT_CELSIUS",
    "UNIT_FAHRENHEIT",
]
