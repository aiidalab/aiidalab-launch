#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
.. currentmodule:: fixtures
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>

Provide fixtures for all tests.
"""

import click
import pytest


@pytest.fixture(auto_use=True)
def app_config(tmp_path, monkeypatch):
    app_config_dir = tmp_path.joinpath("app_dirs")
    monkeypatch.setattr(click, "get_app_dir", lambda: str(app_config_dir))
    yield
