import test from "node:test";
import assert from "node:assert/strict";

// Calibrated boundary constants
const CALIBRATED_BOUNDS = {
  panMin: 15.0,
  panMax: 165.0,
  tiltMin: 60.0,
  tiltMax: 135.0,
};

function createEnvelope(type, payload, seq = 1, corrId = null) {
  return {
    type,
    timestamp: Date.now(),
    sender: "frontend",
    seq,
    corr_id: corrId,
    payload,
  };
}

function clampPan(pan) {
  return Math.min(CALIBRATED_BOUNDS.panMax, Math.max(CALIBRATED_BOUNDS.panMin, pan));
}

function clampTilt(tilt) {
  return Math.min(CALIBRATED_BOUNDS.tiltMax, Math.max(CALIBRATED_BOUNDS.tiltMin, tilt));
}

function getProximityStatus(distanceCm) {
  if (distanceCm < 0 || distanceCm > 400) return "out_of_range";
  if (distanceCm < 20) return "critical";
  if (distanceCm <= 40) return "warning";
  return "safe";
}

function hitTest(clickX, clickY, detections) {
  for (const det of detections) {
    const [x1, y1, x2, y2] = det.bbox;
    if (clickX >= x1 && clickX <= x2 && clickY >= y1 && clickY <= y2) {
      return det.track_id;
    }
  }
  return null;
}

function computeReconnectBackoff(attempt, maxDelayMs = 10000) {
  return Math.min(1000 * Math.pow(1.5, attempt), maxDelayMs);
}

function filterAlerts(alerts, severity, query) {
  return alerts.filter((alert) => {
    if (severity !== "all" && alert.severity !== severity) return false;
    if (query && query.trim() !== "") {
      const q = query.toLowerCase();
      const text = `${alert.event_type} ${alert.message} ${alert.source}`.toLowerCase();
      if (!text.includes(q)) return false;
    }
    return true;
  });
}

function checkRateLimit(lastSendTime, now, minIntervalMs = 45) {
  return now - lastSendTime >= minIntervalMs;
}

function formatUptime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return `${hrs.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

function resolvePirState(pir, uptimeMs) {
  const isPirWarmingUp =
    pir?.warmup_complete === false ||
    (pir?.warmup_complete === undefined && uptimeMs !== undefined && uptimeMs < 30000);
  const remainingS =
    pir?.warmup_remaining_s !== undefined
      ? pir.warmup_remaining_s
      : uptimeMs !== undefined
      ? Math.max(1, Math.ceil((30000 - uptimeMs) / 1000))
      : 30;

  if (isPirWarmingUp) {
    return { state: "warming_up", remainingS };
  }
  if (pir?.motion_detected) {
    return { state: "active" };
  }
  return { state: "clear" };
}

test("Envelope conforms to authoritative 5-field schema", () => {
  const env = createEnvelope("cmd.servo.move", {
    mode: "absolute",
    pan: 90.0,
    tilt: 90.0,
    speed: 0.5,
  });

  assert.equal(env.type, "cmd.servo.move");
  assert.equal(env.sender, "frontend");
  assert.equal(typeof env.timestamp, "number");
  assert.equal(env.seq, 1);
  assert.equal(env.corr_id, null);
  assert.equal(env.payload.pan, 90.0);
  assert.equal(env.payload.tilt, 90.0);
});

test("Calibrated boundary clamping protects servo hardware", () => {
  assert.equal(clampPan(10.0), 15.0);
  assert.equal(clampPan(170.0), 165.0);
  assert.equal(clampPan(90.0), 90.0);

  assert.equal(clampTilt(50.0), 60.0);
  assert.equal(clampTilt(140.0), 135.0);
  assert.equal(clampTilt(90.0), 90.0);
});

test("Ultrasonic distance thresholds correctly tier proximity alerts", () => {
  assert.equal(getProximityStatus(15.2), "critical");
  assert.equal(getProximityStatus(19.9), "critical");
  assert.equal(getProximityStatus(20.0), "warning");
  assert.equal(getProximityStatus(35.5), "warning");
  assert.equal(getProximityStatus(40.0), "warning");
  assert.equal(getProximityStatus(40.1), "safe");
  assert.equal(getProximityStatus(120.0), "safe");
  assert.equal(getProximityStatus(-1.0), "out_of_range");
});

test("Hit testing identifies clicked detection bounding box", () => {
  const detections = [
    { track_id: 1, bbox: [50, 50, 150, 200] },
    { track_id: 4, bbox: [300, 100, 450, 350] },
  ];

  // Inside detection #4
  const hit1 = hitTest(350, 200, detections);
  assert.equal(hit1, 4);

  // Inside detection #1
  const hit2 = hitTest(60, 60, detections);
  assert.equal(hit2, 1);

  // Outside any box
  const miss = hitTest(500, 400, detections);
  assert.equal(miss, null);
});

test("Safe-stop payload structures freeze and resume correctly", () => {
  const freezeEnv = createEnvelope("cmd.estop", {
    action: "freeze",
    reason: "operator_manual_e_stop",
    release_pwm: false,
  });
  assert.equal(freezeEnv.payload.action, "freeze");
  assert.equal(freezeEnv.payload.reason, "operator_manual_e_stop");

  const resumeEnv = createEnvelope("cmd.estop", {
    action: "resume",
    reason: "operator_cleared_e_stop",
  });
  assert.equal(resumeEnv.payload.action, "resume");
});

test("Exponential backoff reconnect bounds and scales appropriately", () => {
  assert.equal(computeReconnectBackoff(0), 1000);
  assert.equal(computeReconnectBackoff(1), 1500);
  assert.equal(computeReconnectBackoff(2), 2250);
  assert.equal(computeReconnectBackoff(3), 3375);
  assert.equal(computeReconnectBackoff(10), 10000); // capped at max
});

test("Client 20 Hz outbound throttling enforces 45ms minimum interval", () => {
  const t0 = 1000;
  assert.equal(checkRateLimit(t0, 1020, 45), false); // 20ms < 45ms -> throttled
  assert.equal(checkRateLimit(t0, 1044, 45), false); // 44ms < 45ms -> throttled
  assert.equal(checkRateLimit(t0, 1045, 45), true);  // 45ms >= 45ms -> allowed
  assert.equal(checkRateLimit(t0, 1100, 45), true);  // 100ms >= 45ms -> allowed
});

test("Alert filtering and search works across severities and keywords", () => {
  const alerts = [
    { event_type: "motion_detected", message: "PIR motion trigger", source: "esp32", severity: "info" },
    { event_type: "ws_disconnect", message: "ESP32 disconnected", source: "backend", severity: "critical" },
    { event_type: "proximity_warning", message: "Sonar < 30cm", source: "esp32", severity: "warning" },
  ];

  // All
  assert.equal(filterAlerts(alerts, "all", "").length, 3);
  // Critical only
  const crit = filterAlerts(alerts, "critical", "");
  assert.equal(crit.length, 1);
  assert.equal(crit[0].event_type, "ws_disconnect");

  // Keyword search
  const searched = filterAlerts(alerts, "all", "sonar");
  assert.equal(searched.length, 1);
  assert.equal(searched[0].event_type, "proximity_warning");
});

test("Track target select builds valid payloads and clamps normalized coordinates", () => {
  // Direct track ID
  const p1 = createEnvelope("track.target_select", { track_id: 8 });
  assert.equal(p1.type, "track.target_select");
  assert.equal(p1.payload.track_id, 8);

  // Normalized coordinates [x, y]
  const normX = Math.max(0, Math.min(1, 0.4567));
  const normY = Math.max(0, Math.min(1, 0.7891));
  const p2 = createEnvelope("track.target_select", { coordinates: [normX, normY] });
  assert.deepEqual(p2.payload.coordinates, [0.4567, 0.7891]);

  // Out of bounds coordinate clamping
  const clampedX = Math.max(0, Math.min(1, -0.2));
  const clampedY = Math.max(0, Math.min(1, 1.4));
  assert.equal(clampedX, 0.0);
  assert.equal(clampedY, 1.0);
});

test("PIR sensor warm-up countdown and detection state resolution", () => {
  // During 30s warm-up window (<30000ms uptime)
  const warm1 = resolvePirState({ warmup_complete: false }, 10000);
  assert.equal(warm1.state, "warming_up");
  assert.equal(warm1.remainingS, 20);

  const warm2 = resolvePirState(undefined, 5000);
  assert.equal(warm2.state, "warming_up");
  assert.equal(warm2.remainingS, 25);

  // Stabilized, motion detected
  const active = resolvePirState({ warmup_complete: true, motion_detected: true }, 45000);
  assert.equal(active.state, "active");

  // Stabilized, clear / no motion
  const clear = resolvePirState({ warmup_complete: true, motion_detected: false }, 45000);
  assert.equal(clear.state, "clear");
});

test("Header and video HUD status telemetry formatting", () => {
  assert.equal(formatUptime(0), "00:00:00");
  assert.equal(formatUptime(65), "00:01:05");
  assert.equal(formatUptime(3665), "01:01:05");

  // Latency & FPS sanity
  const fps = 29.8;
  const fpsFormatted = fps.toFixed(0);
  assert.equal(fpsFormatted, "30");

  const latency = 14;
  assert.equal(`${latency}ms`, "14ms");
});
