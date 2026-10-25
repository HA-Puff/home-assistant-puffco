"""Bond clearing must not scan when a link client already exists."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from puffco_ble.client import PuffcoClient


def test_clear_session_bond_unpairs_current_client_without_scanning():
    client = PuffcoClient("0C:43:14:B7:91:9C")
    bleak = MagicMock()
    bleak.unpair = AsyncMock(return_value=True)
    bleak.reset_pairing_cache = MagicMock()
    client._client = bleak

    with patch(
        "puffco_ble.client.find_device_by_address",
        side_effect=AssertionError("scan"),
    ):
        removed = asyncio.run(client.clear_session_bond())

    assert removed is True
    bleak.unpair.assert_awaited_once()
    bleak.reset_pairing_cache.assert_called_once()
