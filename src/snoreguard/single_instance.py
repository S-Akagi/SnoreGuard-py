"""多重起動の防止（Windows の名前付きミューテックス）。"""

import logging
import sys

logger = logging.getLogger(__name__)

_ERROR_ALREADY_EXISTS = 183
_handle = None  # プロセス終了までミューテックスを保持する


def acquire(name: str = "Local\\SnoreGuard") -> bool:
    """このプロセスが唯一のインスタンスなら True。Windows 以外は常に True。"""
    global _handle
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPCVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        _handle = kernel32.CreateMutexW(None, False, name)
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            logger.warning("SnoreGuard は既に起動しています")
            return False
        return True
    except Exception as e:  # noqa: BLE001 - 判定不能時は起動を妨げない
        logger.warning(f"多重起動チェックに失敗: {e}")
        return True
