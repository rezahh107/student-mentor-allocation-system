from __future__ import annotations

import json
import pathlib

from sma.repo_doctor.core import DoctorConfig, RepoDoctor
from sma.repo_doctor.clock import tehran_clock


def test_adds_src_prefix_phase6(tmp_path: pathlib.Path) -> None:
    src_dir = tmp_path / "src" / "phase6_import_to_sabt"
    src_dir.mkdir(parents=True)
    file_path = src_dir / "consumer.py"
    file_path.write_text(
        "from phase6_import_to_sabt.exporter_service import ImportToSabtExporter\n",
        encoding="utf-8",
    )

    config = DoctorConfig(root=tmp_path, apply=True, clock=tehran_clock())
    doctor = RepoDoctor(config)
    report = doctor.scan()
    doctor.import_doctor.apply(report)

    result = file_path.read_text(encoding="utf-8")
    assert "from sma.phase6_import_to_sabt.exporter_service" in result

    init_path = src_dir / "__init__.py"
    assert init_path.exists()

    backup_path = file_path.with_suffix(".py.bak")
    assert backup_path.exists()

    delta = json.loads((tmp_path / "reports" / "import_delta.json").read_text(encoding="utf-8"))
    assert str(file_path) in delta
