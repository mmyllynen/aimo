from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.production_smoke import main


class ProductionSmokeTests(unittest.TestCase):
    def test_smoke_script_runs_without_live_integrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "aimo.conf"
            log = Path(tmpdir) / "bot.log"
            config.write_text(
                "\n".join(
                    (
                        "[bot]",
                        "language = fi",
                        "[storage]",
                        f"database_path = {Path(tmpdir) / 'aimo.sqlite3'}",
                        f"artifact_path = {Path(tmpdir) / 'artifacts'}",
                        f"raw_gpx_path = {Path(tmpdir) / 'raw_gpx'}",
                    )
                ),
                encoding="utf-8",
            )
            log.write_text("2026-06-17 10:00:00 INFO __main__: Starting Aimo Discord runtime.\n", encoding="utf-8")

            status = main(["--config", str(config), "--log", str(log)])

        self.assertEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
