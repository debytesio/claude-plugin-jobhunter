"""Platform-aware loader for the _jh_core native module."""

import importlib.util
import os
import platform
import sys


def _get_platform_dir():
    system = sys.platform
    machine = platform.machine().lower()
    if system == 'win32':
        return 'win_amd64'
    elif system == 'linux':
        return 'linux_x86_64'
    elif system == 'darwin':
        return 'macos_arm64' if machine == 'arm64' else 'macos_x86_64'
    raise ImportError(f"Unsupported platform: {system}/{machine}")


def _load_native():
    plat_dir = _get_platform_dir()
    pkg_dir = os.path.dirname(__file__)
    bin_dir = os.path.join(pkg_dir, plat_dir)
    if not os.path.isdir(bin_dir):
        raise ImportError(
            f"No _jh_core binary for {plat_dir}. "
            f"Supported: win_amd64, linux_x86_64, macos_x86_64, macos_arm64")
    for f in os.listdir(bin_dir):
        if f.startswith('_jh_core') and (f.endswith('.pyd') or f.endswith('.so')):
            spec = importlib.util.spec_from_file_location(
                '_jh_core', os.path.join(bin_dir, f))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(f"No _jh_core binary found in {bin_dir}")


_native = _load_native()

# Re-export all public symbols from native module
import types as _types
for _name in dir(_native):
    if not _name.startswith('_'):
        _obj = getattr(_native, _name)
        if not isinstance(_obj, _types.ModuleType):
            globals()[_name] = _obj
