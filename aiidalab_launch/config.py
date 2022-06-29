# __future__ import needed for classmethod factory functions; should be dropped
# with py 3.10.
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

import toml

from .profile import Profile

MAIN_PROFILE_NAME = "default"


@dataclass
class Config:
    profiles: list[Profile] = field(default_factory=lambda: [Profile()])
    default_profile: str = MAIN_PROFILE_NAME

    # The configuration is always stored to disk beginning with version
    # 2022.1012, which means we assume that if no configuration is stored
    # we cannot make any assumptions about the latest applicable version.
    version: str | None = None

    @classmethod
    def loads(cls, blob: str) -> Config:
        loaded_config = toml.loads(blob)
        config = deepcopy(loaded_config)
        config["profiles"] = []
        for name, profile in loaded_config.pop("profiles", dict()).items():
            extra_mounts = (
                set(profile.pop("extra_mounts")) if "extra_mounts" in profile else set()
            )
            config["profiles"].append(
                Profile(name=name, extra_mounts=extra_mounts, **profile)
            )
        return cls(**config)

    def dumps(self) -> str:
        config = asdict(self)
        config["profiles"] = {
            profile.pop("name"): profile for profile in config.pop("profiles", [])
        }
        return toml.dumps(config)

    @classmethod
    def load(cls, path: Path) -> Config:
        return cls.loads(path.read_text())

    def save(self, path: Path, safe: bool = True) -> None:
        path.parent.mkdir(exist_ok=True, parents=True)
        if safe:
            path_tmp = path.with_suffix(f".{uuid4()!s}")
            path_tmp.write_text(self.dumps())
            path_tmp.replace(path)
        else:
            path.write_text(self.dumps())

    def get_profile(self, name: str) -> Profile:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise ValueError(f"Did not find profile with name '{name}'.")
