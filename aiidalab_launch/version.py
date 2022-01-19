# -*- coding: utf-8 -*-

"""
This module contains project version information.

.. currentmodule:: aiidalab_launch.version
.. moduleauthor:: Carl Simon Adorf <simon.adorf@epfl.ch>
"""

try:
    from dunamai import Version, get_version

    __version__ = Version.from_git().serialize()
except RuntimeError:
    __version__ = get_version("aiidalab-launch").serialize()
except ImportError:
    __version__ = "v2022.1008"
