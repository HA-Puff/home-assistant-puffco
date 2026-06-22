"""Command-line validation harness for Puffco BLE."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from puffco_ble.client import PuffcoClient
from puffco_ble.encoding import parse_rgb_hex
from puffco_ble.protocol import scan_ble_devices, scan_peak_pro_devices

LOG_DIR = Path(os.environ.get("PUFFCO_LOG_DIR", "logs"))


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_result(command: str, payload: dict) -> None:
    path = LOG_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{command}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Logged to {path}")


async def cmd_scan(args: argparse.Namespace) -> int:
    timeout = args.timeout
    print(f"Scanning ({timeout:.0f}s)...")
    if args.all:
        devices = await scan_ble_devices(timeout=timeout)
        if not devices:
            print("FAIL: No BLE devices found at all")
            print("Tip: Enable Bluetooth, stay near the device, try pairing mode (blue bar).")
            return 1
        print(f"Found {len(devices)} BLE device(s):")
        for device, adv in sorted(devices, key=lambda x: x[0].name or ""):
            name = device.name or adv.local_name or "(no name)"
            print(f"  {name!r}  {device.address}  uuids={adv.service_uuids}")
        print("\nIf you see your Puffco above, use its MAC with --mac (scan filter may miss it).")
        _log_result("scan_all", {"devices": [d.address for d, _ in devices]})
        return 0

    devices = await scan_peak_pro_devices(timeout=timeout)
    if not devices:
        print("FAIL: No Puffco devices matched the filter")
        print("Try:  puffco-cli scan --all")
        print("Then connect with the MAC from Windows Settings or the --all list.")
        return 1
    for device, adv in devices:
        print(f"PASS: {device.name!r} {device.address} uuids={adv.service_uuids}")
    _log_result("scan", {"devices": [d.address for d, _ in devices]})
    return 0


def _mac(args: argparse.Namespace) -> str:
    mac = args.mac or os.environ.get("PUFFCO_MAC")
    if not mac:
        print("ERROR: Provide --mac or set PUFFCO_MAC", file=sys.stderr)
        sys.exit(2)
    return mac


async def cmd_info(args: argparse.Namespace) -> int:
    mac = _mac(args)
    async with PuffcoClient(mac) as client:
        data = await client.fetch_data()
        info = {
            "address": mac,
            "device_name": data.device_name,
            "model": data.model_name,
            "firmware": data.firmware,
            "protocol": data.protocol,
            "total_dabs": data.total_dabs,
            "trip_dabs": data.trip_dabs,
            "dabs_per_day": data.dabs_per_day,
            "heater_temp_c": data.heater_temp_c,
            "profile_temp_c": data.profile_temp_c,
            "profile_temps_c": data.profile_temps_c,
            "active_profile": data.active_profile,
            "operating_state": data.operating_state,
            "battery_percent": data.battery_percent,
            "lantern_on": data.lantern_on,
            "stealth_mode": data.stealth_mode,
        }
        print(json.dumps(info, indent=2))
        _log_result("info", info)
    print("PASS: info")
    return 0


async def cmd_auth_test(args: argparse.Namespace) -> int:
    async with PuffcoClient(_mac(args)) as client:
        ok = await client.auth_test()
    print("PASS: auth-test" if ok else "FAIL: auth-test")
    return 0 if ok else 1


async def cmd_read(args: argparse.Namespace) -> int:
    async with PuffcoClient(_mac(args)) as client:
        if args.metric == "dabs":
            data = await client.fetch_data()
            out = {
                "total_dabs": data.total_dabs,
                "trip_dabs": data.trip_dabs,
                "dabs_per_day": data.dabs_per_day,
            }
        elif args.metric == "temp":
            data = await client.fetch_data()
            out = {
                "heater_temp_c": data.heater_temp_c,
                "profile_temp_c": data.profile_temp_c,
                "active_profile": data.active_profile,
                "operating_state": data.operating_state,
            }
        else:
            print(f"Unknown metric {args.metric}", file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2))
        _log_result(f"read_{args.metric}", out)
    print(f"PASS: read {args.metric}")
    return 0


async def cmd_set_temp(args: argparse.Namespace) -> int:
    profile = args.profile - 1
    if profile not in range(4):
        print("Profile must be 1-4", file=sys.stderr)
        return 2
    async with PuffcoClient(_mac(args)) as client:
        await client.set_profile_temperature(profile, args.celsius)
        read_back = await client.bleak.get_profile_temp(profile)
    ok = abs(read_back - args.celsius) < 1.0
    print(f"Set profile {args.profile} to {args.celsius}°C, read back {read_back:.1f}°C")
    print("PASS: set-temp" if ok else "FAIL: set-temp (read-back mismatch)")
    return 0 if ok else 1


async def cmd_start(args: argparse.Namespace) -> int:
    async with PuffcoClient(_mac(args)) as client:
        await client.start_session()
        state = await client.bleak.get_operating_state()
    print(f"Operating state after start: {state}")
    print("PASS: start (command sent)")
    return 0


async def cmd_abort(args: argparse.Namespace) -> int:
    async with PuffcoClient(_mac(args)) as client:
        await client.abort_session()
        state = await client.bleak.get_operating_state()
    print(f"Operating state after abort: {state}")
    print("PASS: abort (command sent)")
    return 0


async def cmd_color(args: argparse.Namespace) -> int:
    r, g, b = parse_rgb_hex(args.rgb)
    async with PuffcoClient(_mac(args)) as client:
        await client.set_lantern_color_rgb(r, g, b)
        if args.lantern_on:
            await client.set_lantern_enabled(True)
    print(f"PASS: color rgb({r},{g},{b})")
    return 0


async def cmd_lantern(args: argparse.Namespace) -> int:
    enabled = args.state == "on"
    async with PuffcoClient(_mac(args)) as client:
        await client.set_lantern_enabled(enabled)
    print(f"PASS: lantern {args.state}")
    return 0


async def cmd_unpair(args: argparse.Namespace) -> int:
    mac = _mac(args)
    client = PuffcoClient(mac)
    removed = await client.unpair()
    if removed:
        print(f"PASS: unpair (removed stale bond for {mac})")
    else:
        print(f"PASS: unpair (no existing bond for {mac})")
    print("Put the Peak in pairing mode (blue bar) before the next connect.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Puffco BLE validation CLI")
    parser.add_argument("--mac", help="Device Bluetooth MAC address")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Scan for Peak Pro devices")
    scan_p.add_argument(
        "--all",
        action="store_true",
        help="List every BLE device (use to find MAC when filter misses Puffco)",
    )
    scan_p.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Scan duration in seconds (default: 15)",
    )
    scan_p.set_defaults(func=cmd_scan)

    sub.add_parser("info", help="Device info and protocol").set_defaults(func=cmd_info)
    sub.add_parser("auth-test", help="Verify authenticated reads").set_defaults(
        func=cmd_auth_test
    )

    read_p = sub.add_parser("read", help="Read metrics")
    read_p.add_argument("metric", choices=["dabs", "temp"])
    read_p.set_defaults(func=cmd_read)

    temp_p = sub.add_parser("set-temp", help="Set profile temperature (°C)")
    temp_p.add_argument("--profile", type=int, default=1)
    temp_p.add_argument("--celsius", type=float, required=True)
    temp_p.set_defaults(func=cmd_set_temp)

    sub.add_parser("start", help="Start heat cycle").set_defaults(func=cmd_start)
    sub.add_parser("abort", help="Abort/stop the current heat cycle").set_defaults(
        func=cmd_abort
    )

    color_p = sub.add_parser("color", help="Set lantern static color")
    color_p.add_argument("--rgb", required=True, help="Hex RGB e.g. FF0000")
    color_p.add_argument("--lantern-on", action="store_true")
    color_p.set_defaults(func=cmd_color)

    lantern_p = sub.add_parser("lantern", help="Turn lantern on/off")
    lantern_p.add_argument("state", choices=["on", "off"])
    lantern_p.set_defaults(func=cmd_lantern)

    sub.add_parser(
        "unpair",
        help="Remove the stale Windows bond so the Peak can pair fresh",
    ).set_defaults(func=cmd_unpair)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)
    rc = asyncio.run(args.func(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
