import ctypes
import os
import signal
import sys
import threading
import time
from collections.abc import Callable

from fastmcp import FastMCP


def _install_signal_handlers() -> None:
    if threading.current_thread() is not threading.main_thread():
        return

    def handle_shutdown(signum: int, frame: object) -> None:
        os._exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_shutdown)


def _is_windows_process_alive(pid: int) -> bool:
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return True
    exit_code = ctypes.c_ulong()
    result = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    return bool(result and exit_code.value == still_active)


def _start_windows_parent_monitor(
    parent_pid: int | None = None,
    is_alive: Callable[[int], bool] = _is_windows_process_alive,
) -> None:
    if sys.platform != "win32":
        return

    watched_pid = parent_pid or os.getppid()

    def monitor_parent() -> None:
        while True:
            if not is_alive(watched_pid):
                os._exit(0)
            time.sleep(2)

    threading.Thread(target=monitor_parent, daemon=True, name="grok-search-parent-monitor").start()


def run_stdio(mcp: FastMCP) -> None:
    _install_signal_handlers()
    _start_windows_parent_monitor()
    try:
        mcp.run(transport="stdio", show_banner=False)
    except KeyboardInterrupt:
        pass
    finally:
        os._exit(0)
