from __future__ import annotations

from pathlib import Path

import jinja2


def test_role_display_rtl(tmp_path):
    templates = Path("src/ui/templates")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(templates)))
    template = env.get_template("auth_dashboard.html")
    html = template.render(principal={"role": "ADMIN", "center_scope": "ALL"})
    assert "dir=\"rtl\"" in html
    assert "ADMIN" in html
    assert "ALL" in html
