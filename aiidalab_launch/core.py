#!/usr/bin/env python
# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

import toml

MAIN_PROFILE_NAME = "default"


@dataclass
class Profile:
    name: str = MAIN_PROFILE_NAME
    port: int = 8888
    default_apps: list[str] = field(default_factory=lambda: ["aiidalab-widgets-base"])
    system_user: str = "aiida"
    image: str = "aiidalab/aiidalab-docker-stack:latest"
    home_mount: str = field(
        default_factory=lambda: str(Path.home().joinpath("aiidalab"))
    )

    def container_name(self):
        return f"aiidalab_{self.name}"

    def environment(self, jupyter_token):
        return {
            "AIIDALAB_DEFAULT_APPS": " ".join(self.default_apps),
            "JUPYTER_TOKEN": str(jupyter_token),
            "SYSTEM_USER": self.system_user,
        }

    def dumps(self):
        return toml.dumps({k: v for k, v in asdict(self).items() if k != "name"})

    @classmethod
    def loads(cls, name, s):
        return cls(name=name, **toml.loads(s))


@dataclass
class Config:
    profiles: list[Profile] = field(default_factory=lambda: [Profile()])
    default_profile: str = MAIN_PROFILE_NAME

    @classmethod
    def loads(cls, blob):
        config = toml.loads(blob)
        config["profiles"] = [
            Profile(name=name, **profile)
            for name, profile in config.pop("profiles", dict()).items()
        ]
        return cls(**config)

    def dumps(self):
        config = asdict(self)
        config["profiles"] = {
            profile.pop("name"): profile for profile in config.pop("profiles", [])
        }
        return toml.dumps(config)

    @classmethod
    def load(cls, path):
        return cls.loads(path.read_text())

    def save(self, path, safe=True):
        path.parent.mkdir(exist_ok=True)
        if safe:
            path_tmp = path.with_suffix(f".{uuid4()!s}")
            path_tmp.write_text(self.dumps())
            path_tmp.replace(path)
        else:
            path.write_text(self.dumps())

    def get_profile(self, name):
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise ValueError(f"Did not find profile with name '{name}'.")
