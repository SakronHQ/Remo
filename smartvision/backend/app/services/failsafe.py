"""
SmartVision - Failsafe & Heartbeat Watchdog Service
Continuously monitors ESP32-S3 liveness, issues periodic 500ms sys.ping queries,
and triggers safe-stop emergency holds if communication lapses for > 1200ms.
"""

import asyncio
import logging
import time
from typing import Any, Optional

from ..config import settings
from .connection_hub import ConnectionHub
from .state_manager import SystemStateManager

logger = logging.getLogger("SmartVision.Failsafe")


class FailsafeService:
    """
    Supervises system health and communication link liveness.
    """

    def __init__(
        self,
        state_manager: SystemStateManager,
        hub: ConnectionHub,
        tracking_pipeline: Optional[Any] = None,
    ):
        self.state = state_manager
        self.hub = hub
        self.pipeline = tracking_pipeline
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Starts background heartbeat watchdog task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._watchdog_loop(), name="FailsafeWatchdog")
            logger.info("Failsafe watchdog started")

    async def stop(self) -> None:
        """Stops background watchdog."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Failsafe watchdog stopped")

    async def trigger_estop(self, reason: str = "operator_e_stop", action: str = "freeze") -> None:
        """Activates emergency stop across state manager and hardware."""
        self.state.set_estop(True, reason=reason)
        if self.pipeline:
            self.pipeline.stop_tracking()
        # Dispatch to ESP32
        estop_msg = self.hub.create_envelope(
            msg_type="cmd.estop",
            payload={"action": action, "reason": reason},
            corr_id=f"estop_{int(time.time()*1000)}",
        )
        await self.hub.send_to_device(estop_msg)

        # Broadcast alert to all web operators
        alert_msg = self.hub.create_envelope(
            msg_type="alert.event",
            payload={
                "event_id": f"estop_evt_{int(time.time()*1000)}",
                "event_type": "estop_activated",
                "severity": "critical",
                "source": "backend",
                "message": f"Emergency Stop Engaged ({reason})",
                "action_taken": "motion_halted",
                "buzzer_activated": True,
            },
        )
        await self.hub.broadcast_to_clients(alert_msg)

    async def reset_estop(self) -> None:
        """Clears emergency stop condition."""
        self.state.set_estop(False, reason="cleared")
        resume_msg = self.hub.create_envelope(
            msg_type="cmd.estop",
            payload={"action": "resume"},
            corr_id=f"resume_{int(time.time()*1000)}",
        )
        await self.hub.send_to_device(resume_msg)

    async def _watchdog_loop(self) -> None:
        """Periodic background loop sending heartbeats and checking timeouts."""
        while self._running:
            try:
                await asyncio.sleep(settings.ESP32_PING_INTERVAL_S)

                # 1. Send periodic sys.ping if device is connected
                if self.hub.is_device_connected:
                    ping_msg = self.hub.create_envelope(
                        msg_type="sys.ping",
                        payload={},
                        corr_id=f"ping_{int(time.time()*1000)}",
                    )
                    await self.hub.send_to_device(ping_msg)

                    # 2. Check time since last message
                    last_hb = self.state.esp32_last_heartbeat_ms
                    if last_hb is not None:
                        elapsed_s = (int(time.time() * 1000) - last_hb) / 1000.0
                        if elapsed_s > settings.ESP32_WATCHDOG_TIMEOUT_S and not self.state.failsafe_active:
                            logger.warning(
                                f"ESP32 watchdog timeout! No response for {elapsed_s:.2f}s "
                                f"(threshold: {settings.ESP32_WATCHDOG_TIMEOUT_S}s)"
                            )
                            self.state.failsafe_active = True
                            if self.pipeline:
                                self.pipeline.stop_tracking()

                            # Alert all web clients
                            alert = self.hub.create_envelope(
                                msg_type="alert.event",
                                payload={
                                    "event_id": f"evt_wd_{int(time.time()*1000)}",
                                    "event_type": "ws_disconnect",
                                    "severity": "critical",
                                    "source": "backend",
                                    "message": f"ESP32-S3 communication watchdog timeout ({elapsed_s:.1f}s without response)",
                                    "action_taken": "failsafe_engaged",
                                    "buzzer_activated": True,
                                },
                            )
                            self.state.add_alert(alert["payload"])
                            await self.hub.broadcast_to_clients(alert)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in failsafe watchdog loop: {e}", exc_info=True)
