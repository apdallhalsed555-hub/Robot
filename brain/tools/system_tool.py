"""
brain/tools/system_tool.py
Tool to check and report the robot's system status (CPU, RAM, Disk, OS).
"""

import os
import sys
import platform
import shutil
import time

try:
    import psutil
except ImportError:
    psutil = None


class SystemTool:
    def __init__(self, ui_state=None):
        self.ui_state = ui_state
        self.start_time = time.time()

    def get_system_status(self) -> str:
        """
        Gathers and returns key diagnostics about the robot's system health.
        """
        # 1. OS & Python Info
        os_name = platform.system()
        os_release = platform.release()
        py_ver = sys.version.split()[0]
        
        # 2. Uptime
        uptime_sec = time.time() - self.start_time
        uptime_str = f"{int(uptime_sec // 3600)}h {int((uptime_sec % 3600) // 60)}m {int(uptime_sec % 60)}s"

        # 3. CPU & RAM (using psutil if available, otherwise fallback)
        cpu_usage = "N/A"
        ram_info = "N/A"
        if psutil:
            try:
                cpu_usage = f"{psutil.cpu_percent(interval=None)}%"
                mem = psutil.virtual_memory()
                used_gb = mem.used / (1024**3)
                total_gb = mem.total / (1024**3)
                ram_info = f"{used_gb:.2f} GB / {total_gb:.2f} GB ({mem.percent}%)"
            except Exception as e:
                cpu_usage = f"Error: {e}"
        else:
            cpu_usage = "psutil module not installed"

        # 4. Disk Info (using standard library shutil)
        disk_info = "N/A"
        try:
            total, used, free = shutil.disk_usage("/")
            used_gb = used / (1024**3)
            total_gb = total / (1024**3)
            disk_percent = (used / total) * 100
            disk_info = f"{used_gb:.1f} GB / {total_gb:.1f} GB ({disk_percent:.1f}%)"
        except Exception as e:
            disk_info = f"Error: {e}"

        # 5. UI status fallback
        ui_status = "Active"
        if self.ui_state and "system_status" in self.ui_state:
            ui_status = self.ui_state["system_status"]

        status_report = (
            f"=== Robot Diagnostics ===\n"
            f"System Status: {ui_status}\n"
            f"Operating System: {os_name} {os_release}\n"
            f"Python Version: {py_ver}\n"
            f"Uptime: {uptime_str}\n"
            f"CPU Usage: {cpu_usage}\n"
            f"RAM Utilization: {ram_info}\n"
            f"Disk Space: {disk_info}"
        )
        return status_report
