import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import receiver_catalog as catalog  # noqa: E402
import openwebrx_client as owrx  # noqa: E402


class ReceiverCapabilityTests(unittest.TestCase):
    def test_source_order_matches_receiver_sidebar(self):
        self.assertEqual(catalog.SOURCE_FILTERS, ("local", "kiwi", "openwebrx", "fmdx", "all"))

    def test_fixed_passband_returns_an_explanation(self):
        caps = catalog.ReceiverCapabilities.fixed_audio("fmdx", "FM-DX")
        decision = caps.decide("passband")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.message, "Fixed passband on this receiver")

    def test_fmdx_frequency_is_shared_and_read_only_by_default(self):
        record = catalog.normalize_receiver({
            "id": "fm:test", "protocol": "fmdx", "endpoint": "https://fm.test",
            "name": "FM test", "control_scope": "shared_server",
        })
        self.assertEqual(record.capabilities.decide("frequency").message,
                         "Shared tuner: changing frequency affects every listener")

    def test_fmdx_control_scope_and_waterfall_kind_are_truthful(self):
        record = catalog.normalize_receiver({
            "id": "fm:test", "protocol": "fmdx", "endpoint": "https://fm.test",
        })
        self.assertEqual(record.capabilities.control_scope, "shared_server")
        self.assertEqual(record.capabilities.waterfall_kind, "audio_spectrum")
        self.assertEqual(record.capabilities.decide("mode").message,
                         "FM mode is controlled by the shared receiver")
        self.assertEqual(record.capabilities.decide("waterfall_pan").message,
                         "Audio spectrum is fixed to 20 kHz")
        self.assertTrue(record.capabilities.decide("volume").allowed)

    def test_shared_frequency_unlocks_only_after_acknowledgement(self):
        caps = catalog.ReceiverCapabilities.fixed_audio("fmdx", "FM-DX")
        self.assertFalse(caps.decide("frequency").allowed)
        self.assertTrue(caps.decide("frequency", shared_control_acknowledged=True).allowed)
        # Per-session receivers never depend on the acknowledgement flag.
        kiwi = catalog.ReceiverCapabilities.kiwi()
        self.assertTrue(kiwi.decide("frequency").allowed)

    def test_unknown_control_names_itself_in_the_message(self):
        decision = catalog.ReceiverCapabilities.kiwi().decide("spectrum_tilt")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.message, "Spectrum Tilt is unavailable on this receiver")

    def test_filtering_all_keeps_priority_order(self):
        records = tuple(catalog.normalize_receiver(item) for item in (
            {"id": "f", "protocol": "fmdx", "endpoint": "https://fm"},
            {"id": "o", "protocol": "openwebrx", "endpoint": "owrxs://owrx"},
            {"id": "k", "protocol": "kiwi", "endpoint": "https://kiwi"},
        ))
        self.assertEqual([item.protocol for item in catalog.filter_receivers(records, "all")],
                         ["kiwi", "openwebrx", "fmdx"])

    def test_source_group_selects_a_different_segment_than_protocol(self):
        lan_kiwi = catalog.normalize_receiver({
            "id": "local:kiwisdr", "protocol": "kiwi", "source_group": "local",
            "endpoint": "http://kiwisdr.local:8073", "name": "Local KiwiSDR",
        })
        self.assertEqual(lan_kiwi.protocol, "kiwi")
        self.assertEqual(lan_kiwi.source_group, "local")
        self.assertEqual(catalog.filter_receivers((lan_kiwi,), "local"), (lan_kiwi,))
        self.assertEqual(catalog.filter_receivers((lan_kiwi,), "kiwi"), ())
        self.assertEqual(catalog.filter_receivers((lan_kiwi,), "all"), (lan_kiwi,))

    def test_unknown_source_filter_falls_back_to_all(self):
        records = (catalog.normalize_receiver({"id": "k", "protocol": "kiwi",
                                               "endpoint": "https://kiwi"}),)
        self.assertEqual(catalog.filter_receivers(records, "nope"), records)


class CatalogMergeTests(unittest.TestCase):
    def test_catalog_merges_all_sources_by_stable_id(self):
        kiwi_rows = (("Kiwi A", "Somewhere", "http://kiwi.test:8073", 1, 4, 1.0, 2.0, "kiwi"),)
        openwebrx_rows = (("OH6AH", "Finland", "owrxs://rx.oh6ah.fi/", 0, 0, 62.0, 25.0, "openwebrx"),)
        local_rows = (catalog.normalize_receiver({
            "id": "local:rtlsdr", "protocol": "local", "source_group": "local",
            "endpoint": "local://rtlsdr", "name": "Local RTL-SDR",
        }),)
        fmdx_rows = ({"name": "FM A", "location": "FM land", "server": "https://fm.test",
                      "lat": 44.4, "lon": 26.1, "used": 0, "total": 0},)
        merged = catalog.merge_catalogs(
            catalog.records_from_kiwi_directory(kiwi_rows),
            catalog.records_from_kiwi_directory(openwebrx_rows),
            local_rows,
            catalog.records_from_fmdx_directory(fmdx_rows),
        )
        self.assertEqual({item.protocol for item in merged},
                         {"kiwi", "openwebrx", "local", "fmdx"})
        self.assertEqual(len({item.id for item in merged}), len(merged))
        self.assertEqual([item.protocol for item in merged],
                         ["local", "kiwi", "openwebrx", "fmdx"])

    def test_openwebrx_endpoint_is_not_classified_as_kiwi(self):
        record = catalog.normalize_receiver({
            "id": "openwebrx:oh6ah", "protocol": "openwebrx",
            "endpoint": "owrxs://rx.oh6ah.fi/", "name": "OH6AH OpenWebRX",
        })
        self.assertEqual(record.protocol, "openwebrx")
        inferred = catalog.normalize_receiver({
            "endpoint": "owrx://receiver.local/", "name": "Inferred",
        })
        self.assertEqual(inferred.protocol, "openwebrx")

    def test_duplicate_ids_are_dropped_and_priority_is_stable(self):
        first = catalog.normalize_receiver({"id": "k", "protocol": "kiwi",
                                            "endpoint": "https://kiwi"})
        duplicate = catalog.normalize_receiver({"id": "k", "protocol": "kiwi",
                                               "endpoint": "https://kiwi-other"})
        merged = catalog.merge_catalogs((first,), (duplicate,))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].endpoint, "https://kiwi")

    def test_static_sources_seed_openwebrx_and_local(self):
        records = catalog.load_static_sources()
        self.assertEqual({item.protocol for item in records}, {"openwebrx", "kiwi"})
        self.assertEqual({item.source_group for item in records}, {"openwebrx", "local"})
        loaded = catalog.load_receiver_catalog(
            kiwi_rows=(("Kiwi A", "Somewhere", "http://kiwi.test:8073", 1, 4, 1.0, 2.0, "kiwi"),),
            fmdx_receivers=({"name": "FM A", "location": "FM land",
                             "server": "https://fm.test", "lat": 1, "lon": 2},),
        )
        self.assertEqual({item.protocol for item in loaded}, {"kiwi", "openwebrx", "fmdx"})
        # The static LAN Kiwi stays protocol="kiwi" but lands in the local segment.
        self.assertEqual({item.source_group for item in loaded},
                         {"kiwi", "openwebrx", "local", "fmdx"})
        self.assertEqual([item.source_group for item in loaded[:3]],
                         ["local", "kiwi", "openwebrx"])

    def test_legacy_row_adapter_round_trips_trailing_fields(self):
        record = catalog.normalize_receiver({
            "name": "Kiwi A", "location": "Somewhere", "endpoint": "https://kiwi",
            "used": 2, "total": 4, "lat": 1.5, "lon": -2.5, "protocol": "kiwi",
        })
        self.assertEqual(
            catalog.legacy_station_row(record),
            ("Kiwi A", "Somewhere", "https://kiwi", 2, 4, 1.5, -2.5, "kiwi"),
        )


class OpenWebRxNegotiationTests(unittest.TestCase):
    def test_foreign_frequency_falls_back_to_announced_profile_start(self):
        session = owrx.OpenWebRxSession("owrxs://rx.test/")
        session.frequency_hz = 1_088_000.0
        session.config.update({
            "center_freq": 145_500_000.0,
            "samp_rate": 1_000_000.0,
            "start_offset_freq": 100_000.0,
        })
        self.assertEqual(session._effective_frequency_hz(), 145_600_000.0)
        self.assertEqual(session.effective_frequency_hz, 145_600_000.0)

    def test_openwebrx_profile_bounds_frequency(self):
        session = owrx.OpenWebRxSession("owrxs://rx.test/")
        session.config.update({
            "center_freq": 1_000_000.0,
            "samp_rate": 2_000_000.0,
            "modes": ["lsb", "usb", "sat"],
        })
        caps = session.negotiated_capabilities()
        self.assertEqual(caps.frequency_ranges_khz, ((0.0, 2000.0),))
        self.assertIn("passband", caps.controls)
        self.assertEqual(caps.modes, ("lsb", "usb"))
        self.assertEqual(caps.control_scope, "per_session")

    def test_openwebrx_without_config_does_not_guess_a_profile(self):
        caps = owrx.OpenWebRxSession("owrxs://rx.test/").negotiated_capabilities()
        self.assertEqual(caps.frequency_ranges_khz, ())
        self.assertEqual(caps.modes, tuple(sorted(owrx.DEFAULT_FILTERS)))


class RememberedViewMigrationTests(unittest.TestCase):
    old_kiwi_payload = {
        "server": "http://kiwi.test:8073", "receiver_type": "kiwi",
        "mode": "LSB", "frequency_khz": 7075.0, "zoom": 8,
    }

    def test_old_remembered_fmdx_view_loads_as_read_only(self):
        loaded = catalog.migrate_remembered_view({
            "server": "https://fm.test", "receiver_type": "fmdx", "frequency_khz": 101700,
        })
        self.assertEqual(loaded["receiver_id"], "fmdx:https://fm.test")
        self.assertEqual(loaded["shared_control"], False)
        self.assertEqual(loaded["protocol"], "fmdx")

    def test_old_kiwi_view_preserves_mode_and_frequency(self):
        loaded = catalog.migrate_remembered_view(self.old_kiwi_payload)
        self.assertEqual((loaded["mode"], loaded["frequency_khz"]), ("LSB", 7075.0))
        self.assertEqual(loaded["receiver_id"], "kiwi:http://kiwi.test:8073")
        self.assertEqual(loaded["shared_control"], False)


if __name__ == "__main__":
    unittest.main()
