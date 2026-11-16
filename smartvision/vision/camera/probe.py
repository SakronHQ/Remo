"""
SmartVision - Camera Hardware Probe & Capability Discovery
Scans USB and virtual camera devices, probes DirectShow/V4L2 endpoints,
and determines supported resolutions, frame rates, and FourCC formats.
"""

import argparse
from dataclasses import asdict, dataclass, field
import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2

from vision.camera.config import (
    CameraBackend,
    STANDARD_FOURCC,
    STANDARD_FPS,
    STANDARD_RESOLUTIONS,
)

# Known DirectShow subtype GUID DWORD mappings to readable format names
DSHOW_FOURCC_MAP: Dict[int, str] = {
    0xE436EB7D: "RGB24",
    0xE436EB7E: "RGB32",
    0xE436EB7C: "RGB555",
    0xE436EB7B: "RGB565",
}


@dataclass
class CameraDeviceInfo:
    """Detailed hardware capability descriptor for a video device."""
    index: int
    is_available: bool
    backend: str
    default_resolution: Tuple[int, int] = (0, 0)
    default_fps: float = 0.0
    default_fourcc: str = "UNKNOWN"
    supported_resolutions: List[Tuple[int, int]] = field(default_factory=list)
    supported_fourccs: List[str] = field(default_factory=list)
    supported_fps: List[float] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializes device info to dictionary."""
        return asdict(self)


class CameraProbe:
    """
    Utility to scan for available cameras and query their hardware capabilities.
    """

    @staticmethod
    def _silence_opencv_logging() -> None:
        """Temporarily suppresses benign C++ backend logging from OpenCV."""
        try:
            if hasattr(cv2, "utils") and hasattr(cv2.utils, "logging"):
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass

    @classmethod
    def probe_available_indices(
        cls,
        max_index: int = 6,
        backend: Optional[int] = None,
    ) -> List[int]:
        """
        Scans camera indices from 0 up to max_index and returns openable indices.
        Verifies both device open and active frame reading.
        """
        cls._silence_opencv_logging()
        if backend is None:
            backend = CameraBackend.resolve_cv_backend(CameraBackend.AUTO)

        available: List[int] = []
        for idx in range(max_index):
            try:
                cap = cv2.VideoCapture(idx, backend)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        available.append(idx)
                cap.release()
            except Exception:
                continue
        return available

    @classmethod
    def probe_device_capabilities(
        cls,
        index: int,
        backend: Optional[int] = None,
        candidate_resolutions: Optional[List[Tuple[int, int]]] = None,
        candidate_fourccs: Optional[List[str]] = None,
        candidate_fps: Optional[List[float]] = None,
    ) -> CameraDeviceInfo:
        """
        Probes a specific camera index to determine actual supported resolutions,
        pixel formats (FourCC), and frame rates.
        """
        cls._silence_opencv_logging()
        if backend is None:
            backend = CameraBackend.resolve_cv_backend(CameraBackend.AUTO)

        if candidate_resolutions is None:
            candidate_resolutions = list(STANDARD_RESOLUTIONS)
        if candidate_fourccs is None:
            candidate_fourccs = list(STANDARD_FOURCC)
        if candidate_fps is None:
            candidate_fps = list(STANDARD_FPS)

        backend_name = "dshow" if backend == getattr(cv2, "CAP_DSHOW", -1) else (
            "v4l2" if backend == getattr(cv2, "CAP_V4L2", -1) else "any"
        )

        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                return CameraDeviceInfo(
                    index=index,
                    is_available=False,
                    backend=backend_name,
                    error_message=f"Failed to open device at index {index}",
                )

            # Query default properties
            def_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            def_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            def_fps = float(cap.get(cv2.CAP_PROP_FPS))
            fourcc_raw = int(cap.get(cv2.CAP_PROP_FOURCC))
            fourcc_int = fourcc_raw & 0xFFFFFFFF
            if fourcc_int in DSHOW_FOURCC_MAP:
                def_fourcc = DSHOW_FOURCC_MAP[fourcc_int]
            else:
                def_fourcc = "".join([chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)]).strip()
                if not def_fourcc or any(ord(c) < 32 or ord(c) > 126 for c in def_fourcc):
                    def_fourcc = "UNKNOWN"

            # Probe resolutions
            supported_res: List[Tuple[int, int]] = []
            for target_w, target_h in candidate_resolutions:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
                actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if (actual_w, actual_h) == (target_w, target_h):
                    ret, _ = cap.read()
                    if ret and (target_w, target_h) not in supported_res:
                        supported_res.append((target_w, target_h))

            # Probe FourCC codecs
            supported_fmts: List[str] = []
            for fmt in candidate_fourccs:
                fourcc_val = cv2.VideoWriter_fourcc(*fmt)
                cap.set(cv2.CAP_PROP_FOURCC, fourcc_val)
                ret, _ = cap.read()
                if ret and fmt not in supported_fmts:
                    supported_fmts.append(fmt)

            # Probe FPS rates
            supported_rates: List[float] = []
            for rate in candidate_fps:
                cap.set(cv2.CAP_PROP_FPS, rate)
                actual_fps = cap.get(cv2.CAP_PROP_FPS)
                if actual_fps > 0 and abs(actual_fps - rate) < 1.0:
                    supported_rates.append(rate)

            # Fallback if specific FPS probing is not supported by driver
            if not supported_rates and def_fps > 0:
                supported_rates.append(def_fps)

            cap.release()

            return CameraDeviceInfo(
                index=index,
                is_available=True,
                backend=backend_name,
                default_resolution=(def_w, def_h),
                default_fps=def_fps,
                default_fourcc=def_fourcc,
                supported_resolutions=supported_res,
                supported_fourccs=supported_fmts,
                supported_fps=supported_rates,
            )

        except Exception as e:
            return CameraDeviceInfo(
                index=index,
                is_available=False,
                backend=backend_name,
                error_message=str(e),
            )

    @classmethod
    def probe_all_devices(
        cls,
        max_index: int = 4,
        backend: Optional[int] = None,
    ) -> List[CameraDeviceInfo]:
        """
        Probes all openable devices up to max_index and queries full capabilities.
        """
        indices = cls.probe_available_indices(max_index=max_index, backend=backend)
        results: List[CameraDeviceInfo] = []
        for idx in indices:
            info = cls.probe_device_capabilities(index=idx, backend=backend)
            results.append(info)
        return results


def run_probe_cli() -> None:
    """CLI utility for probing cameras."""
    parser = argparse.ArgumentParser(
        description="SmartVision USB Camera Probe & Capability Discovery Utility",
    )
    parser.add_argument(
        "--max-index",
        type=int,
        default=5,
        help="Maximum camera index to probe (default: 5)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Probe a specific camera index only",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON results for automated tooling",
    )

    args = parser.parse_args()

    if args.device is not None:
        info = CameraProbe.probe_device_capabilities(args.device)
        devices = [info]
    else:
        devices = CameraProbe.probe_all_devices(max_index=args.max_index)

    if args.json:
        output = [d.to_dict() for d in devices]
        print(json.dumps(output, indent=2))
        return

    print("=" * 78)
    print("        SMARTVISION PC CAMERA DISCOVERY & CAPABILITY PROBE")
    print("=" * 78)

    if not devices or all(not dev.is_available for dev in devices):
        if not devices:
            print("  [WARN] No physical video capture devices detected!")
        else:
            for dev in devices:
                print(f"  [-] Device Index: {dev.index} ({dev.backend.upper()}) - UNAVAILABLE: {dev.error_message}")
        print("         The system will automatically use the Synthetic Test Pattern generator.")
        print("=" * 78)
        return

    for dev in devices:
        if not dev.is_available:
            print(f"\n[-] Device Index: {dev.index} ({dev.backend.upper()}) - UNAVAILABLE")
            print(f"    - Error: {dev.error_message}")
            continue

        print(f"\n[+] Device Index: {dev.index} ({dev.backend.upper()})")
        print(f"    - Default Resolution : {dev.default_resolution[0]}x{dev.default_resolution[1]}")
        print(f"    - Default FourCC     : {dev.default_fourcc}")
        print(f"    - Default FPS        : {dev.default_fps if dev.default_fps > 0 else 'Variable / Driver'}")
        
        res_strs = [f"{w}x{h}" for w, h in dev.supported_resolutions]
        print(f"    - Tested Resolutions : {', '.join(res_strs) if res_strs else 'None confirmed'}")
        print(f"    - Tested FourCC Formats: {', '.join(dev.supported_fourccs) if dev.supported_fourccs else 'None confirmed'}")
        if dev.supported_fps:
            fps_strs = [f"{fps:.0f}" for fps in dev.supported_fps]
            print(f"    - Supported FPS      : {', '.join(fps_strs)}")

    print("\n" + "=" * 78)


if __name__ == "__main__":
    run_probe_cli()
