"""Platform-aware loader for the _jh_core native module.

Auto-downloads binaries from GitHub Releases if Git LFS
pointers weren't resolved (e.g. git-lfs not installed).
"""

import importlib.util
import os
import platform
import sys

REPO = 'debytesio/claude-plugin-jobhunter'
_VERSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    '.claude-plugin', 'plugin.json')


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


def _get_version():
    """Read plugin version from plugin.json."""
    try:
        import json
        with open(_VERSION_FILE) as f:
            return json.load(f).get('version', 'latest')
    except Exception:
        return 'latest'


def _is_lfs_pointer(path):
    """Check if a file is a Git LFS pointer instead of actual binary."""
    try:
        size = os.path.getsize(path)
        if size > 4096:
            return False
        with open(path, 'rb') as f:
            header = f.read(40)
        return header.startswith(b'version https://git-lfs')
    except Exception:
        return False


def _download_binary(bin_path, filename, plat_dir):
    """Download binary from GitHub Release assets."""
    import urllib.request

    version = f'v{_get_version()}'
    asset_name = f'{plat_dir}_{filename}'
    url = (
        f'https://github.com/{REPO}/releases/download/'
        f'{version}/{asset_name}')

    print(f"INFO:     Downloading _jh_core binary for {plat_dir}...")
    try:
        urllib.request.urlretrieve(url, bin_path)
        if os.path.getsize(bin_path) < 4096:
            os.remove(bin_path)
            raise ImportError(
                f"Downloaded file too small — asset may not exist "
                f"at {url}")
        print(f"INFO:     Binary downloaded: {bin_path}")
    except Exception as e:
        raise ImportError(
            f"Failed to download _jh_core from {url}: {e}")


def _load_native():
    plat_dir = _get_platform_dir()
    pkg_dir = os.path.dirname(__file__)
    bin_dir = os.path.join(pkg_dir, plat_dir)
    if not os.path.isdir(bin_dir):
        os.makedirs(bin_dir, exist_ok=True)

    for f in os.listdir(bin_dir):
        if not (f.startswith('_jh_core')
                and (f.endswith('.pyd') or f.endswith('.so'))):
            continue
        bin_path = os.path.join(bin_dir, f)

        # Auto-download if LFS pointer
        if _is_lfs_pointer(bin_path):
            _download_binary(bin_path, f, plat_dir)

        spec = importlib.util.spec_from_file_location(
            '_jh_core', bin_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    raise ImportError(
        f"No _jh_core binary found in {bin_dir}. "
        f"Supported: win_amd64, linux_x86_64, "
        f"macos_x86_64, macos_arm64")


_native = _load_native()

# Re-export all public symbols from native module
import types as _types
for _name in dir(_native):
    if not _name.startswith('_'):
        _obj = getattr(_native, _name)
        if not isinstance(_obj, _types.ModuleType):
            globals()[_name] = _obj
