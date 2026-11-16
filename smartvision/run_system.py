#!/usr/bin/env python3
"""
SmartVision - Unified Multi-Tier System Launcher & Process Supervisor
Phase 8: System Integration & Stack Orchestration.

Launches and monitors the complete 4-tier SmartVision stack with a single command:
  1. FastAPI Central Backend Gateway (Dual WebSockets, MJPEG Stream, REST API)
  2. Next.js Operator Dashboard (App Router Web UI)
  3. (Optional) Mock ESP32-S3 Firmware Client (Virtual PCA9685 servos, HC-SR04 sonar, HC-SR501 PIR)

Features:
  - Automated pre-flight environment and dependency verification
  - Dynamic port conflict detection and health check readiness polling
  - Color-coded multiplexed standard I/O streaming ([BACKEND], [FRONTEND], [ESP32-MOCK])
  - Clean cross-platform process tree termination on SIGINT / SIGTERM (Ctrl+C)
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

# ANSI Color Codes for terminal multiplexing
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_CYAN = "\033[36m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_MAGENTA = "\033[35m"
COLOR_RED = "\033[31m"
COLOR_BLUE = "\033[34m"

# Path definitions
SMARTVISION_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SMARTVISION_DIR, "backend")
FRONTEND_DIR = os.path.join(SMARTVISION_DIR, "frontend")

if os.name == "nt":
    VENV_PYTHON = os.path.join(SMARTVISION_DIR, ".venv", "Scripts", "python.exe")
else:
    VENV_PYTHON = os.path.join(SMARTVISION_DIR, ".venv", "bin", "python")

PYTHON_EXE = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def is_port_available(host: str, port: int) -> bool:
    """Checks whether a TCP port is available on the local interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def stream_output(pipe, prefix: str, color: str, stop_event: threading.Event):
    """Continuously reads lines from subprocess stdout/stderr and prints with color tag."""
    try:
        for line in iter(pipe.readline, ""):
            if stop_event.is_set() and not line:
                break
            line_str = line.strip()
            if line_str:
                print(f"{color}{prefix}{COLOR_RESET} {line_str}", flush=True)
    except (ValueError, OSError):
        pass
    finally:
        pipe.close()


class SystemSupervisor:
    """Supervisor orchestrating child processes across the SmartVision stack."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        frontend_port: int = 3000,
        enable_frontend: bool = True,
        enable_mock_esp32: bool = False,
        force_synthetic: bool = False,
        detector_mode: str = "face",
        debug: bool = False,
        camera_index: Optional[int] = None,
    ):
        self.host = host
        self.port = port
        self.frontend_port = frontend_port
        self.enable_frontend = enable_frontend
        self.enable_mock_esp32 = enable_mock_esp32
        self.force_synthetic = force_synthetic
        self.detector_mode = detector_mode
        self.debug = debug
        self.camera_index = camera_index

        self.processes: Dict[str, subprocess.Popen] = {}
        self.threads: List[threading.Thread] = []
        self.stop_event = threading.Event()
        self._shutting_down = False

    def preflight_check(self) -> bool:
        """Verifies environment, packages, and network ports prior to launch."""
        print(f"{COLOR_BOLD}{COLOR_MAGENTA}[PREFLIGHT]{COLOR_RESET} Running system preflight checks...")

        # 1. Check Python executable
        if not os.path.exists(PYTHON_EXE):
            print(f"{COLOR_RED}[ERROR] Python executable not found: {PYTHON_EXE}{COLOR_RESET}")
            return False
        print(f"  {COLOR_GREEN}✓{COLOR_RESET} Python Runtime: {PYTHON_EXE}")

        # 2. Check Backend Gateway Port
        if not is_port_available(self.host if self.host != "0.0.0.0" else "127.0.0.1", self.port):
            print(f"{COLOR_YELLOW}[WARNING] Backend port {self.port} is already in use.{COLOR_RESET}")

        # 3. Check Frontend Node & npm if frontend enabled
        if self.enable_frontend:
            npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
            try:
                res = subprocess.run([npm_cmd, "--version"], capture_output=True, text=True, timeout=3.0)
                if res.returncode == 0:
                    print(f"  {COLOR_GREEN}✓{COLOR_RESET} Node.js / npm: v{res.stdout.strip()}")
                else:
                    print(f"{COLOR_YELLOW}[WARNING] npm exited with code {res.returncode}{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_YELLOW}[WARNING] npm check failed ({e}). Frontend may fail to launch.{COLOR_RESET}")

        print(f"  {COLOR_GREEN}✓{COLOR_RESET} Synthetic Camera: {'Forced ON' if self.force_synthetic else 'Auto (UVC physical with fallback)'}")
        print(f"  {COLOR_GREEN}✓{COLOR_RESET} Detector Engine: {self.detector_mode}")
        return True

    def start_backend(self) -> subprocess.Popen:
        """Launches Uvicorn FastAPI Central Gateway."""
        env = os.environ.copy()
        env["SMARTVISION_HOST"] = self.host
        env["SMARTVISION_PORT"] = str(self.port)
        env["SMARTVISION_DEBUG"] = "true" if self.debug else "false"
        env["SMARTVISION_FORCE_SYNTHETIC"] = "true" if self.force_synthetic else "false"
        env["SMARTVISION_DETECTOR_MODE"] = self.detector_mode
        if self.camera_index is not None:
            env["SMARTVISION_CAMERA_INDEX"] = str(self.camera_index)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = SMARTVISION_DIR + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

        cmd = [
            PYTHON_EXE,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--log-level",
            "info" if not self.debug else "debug",
        ]

        print(f"{COLOR_BOLD}{COLOR_CYAN}[BACKEND]{COLOR_RESET} Spawning Central Gateway on http://{self.host}:{self.port}...", flush=True)
        proc = subprocess.Popen(
            cmd,
            cwd=SMARTVISION_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.processes["backend"] = proc

        t = threading.Thread(
            target=stream_output,
            args=(proc.stdout, "[BACKEND]", COLOR_CYAN, self.stop_event),
            daemon=True,
        )
        t.start()
        self.threads.append(t)
        return proc

    def start_frontend(self) -> Optional[subprocess.Popen]:
        """Launches Next.js Operator Dashboard."""
        if not self.enable_frontend:
            return None

        env = os.environ.copy()
        env["PORT"] = str(self.frontend_port)
        env["NEXT_PUBLIC_WS_URL"] = f"ws://localhost:{self.port}/ws/client"
        env["NEXT_PUBLIC_API_URL"] = f"http://localhost:{self.port}/api/v1"

        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        cmd = [npm_cmd, "run", "dev", "--", "-p", str(self.frontend_port)]

        print(f"{COLOR_BOLD}{COLOR_GREEN}[FRONTEND]{COLOR_RESET} Spawning Operator Dashboard on http://localhost:{self.frontend_port}...", flush=True)
        proc = subprocess.Popen(
            cmd,
            cwd=FRONTEND_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.processes["frontend"] = proc

        t = threading.Thread(
            target=stream_output,
            args=(proc.stdout, "[FRONTEND]", COLOR_GREEN, self.stop_event),
            daemon=True,
        )
        t.start()
        self.threads.append(t)
        return proc

    def start_mock_esp32(self) -> Optional[subprocess.Popen]:
        """Launches Virtual ESP32-S3 Firmware Client connecting to /ws/device."""
        if not self.enable_mock_esp32:
            return None

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = SMARTVISION_DIR + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

        mock_script = os.path.join(SMARTVISION_DIR, "tests", "mock_esp32_firmware.py")
        cmd = [
            PYTHON_EXE,
            mock_script,
            "--mode",
            "network",
            "--url",
            f"ws://127.0.0.1:{self.port}/ws/device",
            "--interval",
            "0.1",
        ]

        print(f"{COLOR_BOLD}{COLOR_YELLOW}[ESP32-MOCK]{COLOR_RESET} Spawning Virtual ESP32 Hardware Client...", flush=True)
        proc = subprocess.Popen(
            cmd,
            cwd=SMARTVISION_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.processes["esp32_mock"] = proc

        t = threading.Thread(
            target=stream_output,
            args=(proc.stdout, "[ESP32-MOCK]", COLOR_YELLOW, self.stop_event),
            daemon=True,
        )
        t.start()
        self.threads.append(t)
        return proc

    def wait_for_backend_health(self, timeout_s: float = 12.0) -> bool:
        """Polls REST health check until backend indicates successful initialization."""
        health_url = f"http://127.0.0.1:{self.port}/api/v1/health"
        start_t = time.time()
        while time.time() - start_t < timeout_s:
            try:
                import requests
                r = requests.get(health_url, timeout=0.8)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def shutdown(self):
        """Cleanly terminates all child processes and process trees."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.stop_event.set()

        print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}[SHUTDOWN]{COLOR_RESET} Gracefully stopping all SmartVision stack processes...", flush=True)

        for name, proc in list(self.processes.items()):
            if proc.poll() is None:
                print(f"  Stopping {name} (PID: {proc.pid})...", flush=True)
                try:
                    if os.name == "nt":
                        # Terminate full process tree on Windows (essential for node.exe under npm.cmd)
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            capture_output=True,
                            timeout=3.0,
                        )
                        try:
                            proc.wait(timeout=1.0)
                        except Exception:
                            pass
                    else:
                        proc.terminate()
                        proc.wait(timeout=2.0)
                except Exception as e:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        print(f"{COLOR_BOLD}{COLOR_GREEN}[SHUTDOWN]{COLOR_RESET} All processes halted cleanly. Stack offline.", flush=True)

    def run(self):
        """Supervisor main entry loop."""
        print("=" * 76)
        print(f"{COLOR_BOLD}{COLOR_CYAN}  SMARTVISION — Autonomous Pan/Tilt Person Tracking System{COLOR_RESET}")
        print(f"  {COLOR_BOLD}Phase 8: Unified Multi-Tier Stack Launcher{COLOR_RESET}")
        print("=" * 76)

        if not self.preflight_check():
            sys.exit(1)

        # Register OS signal handlers
        def signal_handler(sig, frame):
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # 1. Start Backend Gateway
        self.start_backend()

        # 2. Wait for Backend Readiness
        print(f"{COLOR_MAGENTA}[SUPERVISOR]{COLOR_RESET} Waiting for Gateway API to report ready...")
        if self.wait_for_backend_health():
            print(f"{COLOR_BOLD}{COLOR_GREEN}[READY]{COLOR_RESET} Central Gateway is live and accepting connections!")
        else:
            print(f"{COLOR_YELLOW}[WARNING] Backend did not respond to health check within timeout. Proceeding...{COLOR_RESET}")

        # 3. Start Optional Mock ESP32 Device
        if self.enable_mock_esp32:
            self.start_mock_esp32()

        # 4. Start Frontend Operator Dashboard
        if self.enable_frontend:
            self.start_frontend()

        # Print Access Guide
        print("-" * 76)
        print(f"{COLOR_BOLD}Stack Endpoints:{COLOR_RESET}")
        print(f"  • Operator Web UI:       http://localhost:{self.frontend_port}")
        print(f"  • REST Management API:   http://localhost:{self.port}/api/v1/system/status")
        print(f"  • Live MJPEG Video:      http://localhost:{self.port}/api/v1/stream/video.mjpeg")
        print(f"  • ESP32 WebSocket:       ws://localhost:{self.port}/ws/device")
        print(f"  • Operator WebSocket:    ws://localhost:{self.port}/ws/client")
        print(f"  • Swagger API Docs:      http://localhost:{self.port}/docs")
        print("-" * 76)
        print(f"{COLOR_BOLD}Press Ctrl+C to stop all services gracefully.{COLOR_RESET}\n")

        # Monitor loop
        try:
            while not self.stop_event.is_set():
                for name, proc in self.processes.items():
                    code = proc.poll()
                    if code is not None:
                        print(f"{COLOR_RED}[WARNING] Process '{name}' exited unexpectedly with code {code}{COLOR_RESET}")
                time.sleep(1.0)
        except KeyboardInterrupt:
            self.shutdown()


def main():
    parser = argparse.ArgumentParser(description="SmartVision Unified Multi-Tier Stack Launcher")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Gateway bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Gateway port (default: 8000)")
    parser.add_argument("--frontend-port", type=int, default=3000, help="Next.js frontend port (default: 3000)")
    parser.add_argument("--no-frontend", action="store_true", help="Launch backend gateway only without Next.js UI")
    parser.add_argument("--mock-esp32", action="store_true", help="Launch virtual ESP32 hardware client")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic test pattern video stream")
    parser.add_argument("--detector", "--detector-mode", dest="detector", type=str, default="face", choices=["auto", "face", "mock", "yolo"], help="Person/Face detector mode (default: face)")
    parser.add_argument("--camera-index", type=int, default=None, help="Camera device index (default: 0 for physical webcam, 1 for OBS Virtual Camera)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--check-only", action="store_true", help="Execute preflight checks and exit")
    args = parser.parse_args()

    supervisor = SystemSupervisor(
        host=args.host,
        port=args.port,
        frontend_port=args.frontend_port,
        enable_frontend=not args.no_frontend,
        enable_mock_esp32=args.mock_esp32,
        force_synthetic=args.synthetic,
        detector_mode=args.detector,
        debug=args.debug,
        camera_index=args.camera_index,
    )

    if args.check_only:
        ok = supervisor.preflight_check()
        sys.exit(0 if ok else 1)

    supervisor.run()


if __name__ == "__main__":
    main()
