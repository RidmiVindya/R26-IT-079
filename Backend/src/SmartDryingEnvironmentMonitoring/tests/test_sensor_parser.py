import app.sensor_parser as sensor_parser


def test_corrected_default_calibration_maps_reference_weights(monkeypatch):
    monkeypatch.setattr(sensor_parser, "RAW_ZERO", 78959)
    monkeypatch.setattr(sensor_parser, "COUNTS_PER_KG", 389300.0)
    monkeypatch.setattr(sensor_parser, "_runtime_raw_zero", None)

    assert sensor_parser.raw_to_kg(78959) == 0.0
    assert sensor_parser.raw_to_kg(273609) == 0.5
    assert sensor_parser.raw_to_kg(468259) == 1.0


def test_runtime_tare_excludes_empty_tray(monkeypatch):
    monkeypatch.setattr(sensor_parser, "COUNTS_PER_KG", 389300.0)
    monkeypatch.setattr(sensor_parser, "_runtime_raw_zero", None)

    tray_raw = 120000
    sensor_parser.set_raw_zero(tray_raw)

    assert sensor_parser.raw_to_kg(tray_raw) == 0.0
    assert sensor_parser.raw_to_kg(tray_raw + 194650) == 0.5
