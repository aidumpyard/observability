"""PromptRepo — load/list/save versioned prompts from a directory tree."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_VFILE = re.compile(r"^v(\d+)\.prompt$")
_LIST_KEYS = {"variables", "tags"}


def default_root() -> str:
    return os.environ.get("PRISM_PROMPTS_DIR", os.path.join(os.getcwd(), "prompts"))


@dataclass
class Prompt:
    app: str
    name: str
    version: int
    template: str
    meta: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.app}/{self.name}@v{self.version}"

    @property
    def variables(self) -> list[str]:
        return list(self.meta.get("variables") or [])

    def render(self, **values) -> str:
        """Render with str.format. With no values, return the raw template
        (so prompts containing literal braces don't need escaping when unused)."""
        if not values:
            return self.template
        return self.template.format(**values)


class PromptRepo:
    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or default_root())

    # ---- paths ----
    def _name_dir(self, app: str, name: str) -> Path:
        return self.root / app / name

    # ---- read ----
    def list_apps(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def list_prompts(self, app: str) -> list[str]:
        d = self.root / app
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_dir())

    def versions(self, app: str, name: str) -> list[int]:
        d = self._name_dir(app, name)
        if not d.is_dir():
            return []
        out = []
        for f in d.iterdir():
            m = _VFILE.match(f.name)
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def latest_version(self, app: str, name: str) -> Optional[int]:
        vs = self.versions(app, name)
        return vs[-1] if vs else None

    def load(self, app: str, name: str, version: Optional[int] = None) -> Prompt:
        if version is None:
            version = self.latest_version(app, name)
            if version is None:
                raise FileNotFoundError(f"no prompt '{name}' for app '{app}' under {self.root}")
        path = self._name_dir(app, name) / f"v{version}.prompt"
        if not path.is_file():
            raise FileNotFoundError(f"prompt not found: {path}")
        meta, body = _parse(path.read_text())
        meta.setdefault("version", version)
        return Prompt(app=app, name=name, version=int(meta["version"]), template=body, meta=meta)

    def resolve(self, ref: str) -> Prompt:
        """Load by ref string 'app/name@vN' or 'app/name' (latest)."""
        app_name, _, ver = ref.partition("@")
        app, _, name = app_name.partition("/")
        version = int(ver.lstrip("v")) if ver else None
        return self.load(app, name, version)

    # ---- write (authoring / new versions) ----
    def save(self, app: str, name: str, template: str, *, meta: Optional[dict] = None,
             bump: bool = True) -> Prompt:
        meta = dict(meta or {})
        latest = self.latest_version(app, name)
        version = (latest + 1) if (latest and bump) else (latest or 1)
        meta["version"] = version
        meta.setdefault("created_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        d = self._name_dir(app, name)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"v{version}.prompt").write_text(_format(meta, template))
        return Prompt(app=app, name=name, version=version, template=template, meta=meta)


# ---- frontmatter parsing ---------------------------------------------------

def _parse(text: str) -> tuple[dict, str]:
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            _, front, body = parts
            for line in front.strip().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    k, v = k.strip(), v.strip()
                    if k in _LIST_KEYS:
                        meta[k] = [x.strip() for x in v.split(",") if x.strip()]
                    elif v.isdigit():
                        meta[k] = int(v)
                    else:
                        meta[k] = v
    return meta, body.lstrip("\n")


def _format(meta: dict, body: str) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body.rstrip("\n") + "\n"
