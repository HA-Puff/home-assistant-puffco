"""Lantern effect packing and readback."""

from puffco_ble.constants import LanternAnimation, LanternMode
from puffco_ble.lantern_effects import (
    LANTERN_EFFECT_BY_NAME,
    MOOD_EFFECT_NAMES,
    PROFILE_MOOD_SLOT_BASE,
    pack_lantern_effect,
    parse_lantern_color,
    table_color_slot,
)


def test_color_effects_keep_mode_and_take_rgb():
    pulsing = pack_lantern_effect("Pulsing", 0x11, 0x22, 0x33)
    rotating = pack_lantern_effect("Rotating", 1, 2, 3)
    disco = pack_lantern_effect("Disco", 9, 8, 7)

    assert list(pulsing) == [0x11, 0x22, 0x33, 0x00, 0x05, 0x00, 0x00, 0x00]
    assert list(rotating) == [1, 2, 3, 0x00, 0x15, 0x00, 0x00, 0x00]
    assert list(disco) == [9, 8, 7, 0x00, 0x01, 0x00, 0x00, 0x00]

    for name, mode in (
        ("Pulsing", LanternMode.BREATHING),
        ("Rotating", LanternMode.CIRCLING_SLOW),
        ("Disco", LanternMode.STATIC),
    ):
        effect = LANTERN_EFFECT_BY_NAME[name]
        assert effect.kind == "rgb_mode"
        assert effect.uses_color
        assert effect.mode == mode
        assert effect.preset is None


def test_parse_recolored_effect_from_mode_byte():
    pulsing = bytes(pack_lantern_effect("Pulsing", 0x11, 0x22, 0x33))
    rotating = bytes(pack_lantern_effect("Rotating", 1, 2, 3))
    disco = bytes(pack_lantern_effect("Disco", 9, 8, 7))

    assert parse_lantern_color(pulsing, selected="Pulsing") == (
        (0x11, 0x22, 0x33),
        "Pulsing",
    )
    assert parse_lantern_color(rotating, selected="Rotating") == ((1, 2, 3), "Rotating")
    assert parse_lantern_color(disco, selected="Disco") == ((9, 8, 7), "Disco")

    # Same mode bytes as the rgb modes, so an unmatched selection falls back.
    assert parse_lantern_color(pulsing, selected="Solid")[1] == "Breathing"
    assert parse_lantern_color(rotating, selected="Solid")[1] == "Circling Slow"
    assert parse_lantern_color(disco, selected="Rising")[1] == "Solid"
    assert parse_lantern_color(pulsing, selected="Breathing")[1] == "Breathing"


def test_exclusive_blobs_keep_baked_colors():
    puffcon = LANTERN_EFFECT_BY_NAME["Puffcon 2026"]
    disco_ring = LANTERN_EFFECT_BY_NAME["Disco Ring"]
    assert puffcon.kind == "blob"
    assert puffcon.uses_color is False
    assert puffcon.swatch == (116, 205, 77)
    assert disco_ring.name == "Disco Ring"
    assert LANTERN_EFFECT_BY_NAME["Disco"].kind == "rgb_mode"

    packed = pack_lantern_effect("Puffcon 2026", 1, 2, 3)
    assert bytes(packed) == puffcon.preset
    assert bytes(packed).hex().startswith("a1646c616d70")
    assert parse_lantern_color(packed, selected="Solid") == (
        (116, 205, 77),
        "Puffcon 2026",
    )
    assert parse_lantern_color(bytes(packed) + b"\x00") is None
    assert parse_lantern_color(bytes(packed)[:20]) is None
    assert parse_lantern_color(bytes(packed)[:8])[1] != "Puffcon 2026"


def test_exclusive_moods_use_led_api2_user_arrays():
    mood = LANTERN_EFFECT_BY_NAME["Puffcon 2026"].mood
    assert mood is not None
    assert len(mood.colors) == 128
    assert mood.colors[:8] == bytes([0xED, 0x6F, 0x28, 0, 0xED, 0x6F, 0x28, 0])
    assert len(mood.offsets) == 80
    assert mood.offsets[4:8] == (1024).to_bytes(4, "little")

    table = mood.table_color(5)
    assert list(table) == [255, 14, 1, 1, 0, 0, 0xDD, 0]
    assert table_color_slot(table) == 5
    assert table_color_slot(mood.table_color(6)) == 6
    assert parse_lantern_color(bytes(mood.table_color(6)), selected="Solid") == (
        (116, 205, 77),
        "Puffcon 2026",
    )

    for effect in LANTERN_EFFECT_BY_NAME.values():
        if effect.kind == "blob":
            assert effect.mood is not None
            assert len(effect.mood.colors) == 128

    profile_table = mood.table_color(PROFILE_MOOD_SLOT_BASE + 3)
    assert profile_table[6] == 0xCC
    assert table_color_slot(profile_table) == 4
    assert "Puffcon 2026" in MOOD_EFFECT_NAMES
    assert "Solid" not in MOOD_EFFECT_NAMES

    twin = LANTERN_EFFECT_BY_NAME["Puffcon 2022"].mood.table_color(5)
    assert parse_lantern_color(bytes(twin), selected="Puffcon 2022")[1] == "Puffcon 2022"


def test_parse_yellow_presets_still_named():
    assert parse_lantern_color(bytes(LanternAnimation.PULSING), selected="Solid") == (
        (255, 255, 0),
        "Pulsing",
    )
    assert parse_lantern_color(bytes(LanternAnimation.ROTATING), selected="Solid")[1] == (
        "Rotating"
    )
    assert parse_lantern_color(bytes(LanternAnimation.DISCO_MODE), selected="Breathing")[
        1
    ] == "Disco"
