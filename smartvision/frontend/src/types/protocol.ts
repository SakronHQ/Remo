/**
 * SmartVision Protocol TypeScript Definitions
 * Aligned with docs/protocol.md, backend schemas/protocol.py, and schemas/rest.py.
 */

export type NodeSender = "frontend" | "backend" | "esp32";
export type AlertSeverity = "info" | "warning" | "critical";
export type TrackingMode = "auto_track" | "manual" | "idle" | "patrol";
export type TargetTrackingState = "TRACKING" | "COASTING" | "HOLDING" | "LOST" | "IDLE";
export type SafeStopAction = "freeze" | "center" | "release_pwm" | "resume" | "reset";

export interface SmartVisionEnvelope<T = any> {
  type: string;
  timestamp: number;
  sender: NodeSender;
  seq: number;
  corr_id?: string | null;
  payload: T;
}

export interface ServoBounds {
  panMin: number;
  panMax: number;
  tiltMin: number;
  tiltMax: number;
}

export const CALIBRATED_BOUNDS: ServoBounds = {
  panMin: 15.0,
  panMax: 165.0,
  tiltMin: 60.0,
  tiltMax: 135.0,
};

// Outbound Payloads
export interface ServoMovePayload {
  mode: "absolute" | "relative";
  pan?: number;
  tilt?: number;
  speed?: number;
  step_deg?: number;
  smooth?: boolean;
}

export interface ServoJogPayload {
  delta_pan: number;
  delta_tilt: number;
  speed?: number;
}

export interface ServoCenterPayload {
  speed?: number;
}

export interface ServoPatrolPayload {
  enabled: boolean;
  pan_min?: number;
  pan_max?: number;
  tilt_angle?: number;
  speed_deg_s?: number;
  dwell_time_ms?: number;
}

export interface BuzzerControlPayload {
  action: "beep" | "chirp" | "alarm" | "pulse" | "off";
  duration_ms?: number;
  count?: number;
  interval_ms?: number;
}

export interface SafeStopPayload {
  reason?: string;
  action?: SafeStopAction;
  release_pwm?: boolean;
  details?: string;
}

export interface TrackModeSetPayload {
  mode: TrackingMode;
  target_selection?: string;
  deadband_px?: number;
  smoothing_factor?: number;
  reacquisition_timeout_ms?: number;
}

export interface TrackSelectIdPayload {
  track_id: number;
}

export interface TrackTargetSelectPayload {
  track_id?: number;
  coordinates?: [number, number];
  click_x?: number;
  click_y?: number;
}

export interface ClickToTrackPayload {
  click_x: number;
  click_y: number;
}

// Inbound Payloads
export interface SonarTelemetry {
  distance_cm: number;
  valid: boolean;
  status: "in_range" | "out_of_range" | "timeout";
}

export interface PirTelemetry {
  motion_detected: boolean;
  trigger_count: number;
  last_trigger_ms: number;
  warmup_complete?: boolean;
  warmup_remaining_s?: number;
}

export interface ServosTelemetry {
  pan_angle: number;
  tilt_angle: number;
  pan_target: number;
  tilt_target: number;
  is_moving: boolean;
}

export interface BuzzerTelemetry {
  active: boolean;
  pattern: string;
}

export interface SystemTelemetry {
  uptime_ms: number;
  rssi_dbm: number;
  free_heap_bytes?: number;
  psram_free_bytes?: number;
  cpu_temp_c?: number;
}

export interface SensorTelemetryPayload {
  sonar: SonarTelemetry;
  pir: PirTelemetry;
  servos: ServosTelemetry;
  buzzer: BuzzerTelemetry;
  system: SystemTelemetry;
}

export interface DetectedPerson {
  track_id: number;
  class_name: string;
  confidence: number;
  bbox: [number, number, number, number]; // [x1, y1, x2, y2]
  is_primary?: boolean;
}

export interface ActiveTarget {
  track_id: number;
  class_name: string;
  confidence: number;
  bbox: [number, number, number, number];
  bbox_normalized?: [number, number, number, number];
  centroid: [number, number];
  centroid_normalized?: [number, number];
  error_px: [number, number];
  in_deadband?: boolean;
  state?: TargetTrackingState;
  commanded_delta_deg?: {
    pan: number;
    tilt: number;
  };
}

export interface TrackFrameTargetPayload {
  frame_id: number;
  timestamp_captured: number;
  timestamp_processed: number;
  latency_ms: number;
  frame_dimensions: {
    width: number;
    height: number;
  };
  tracking_mode: TrackingMode;
  target_locked: boolean;
  active_target: ActiveTarget | null;
  all_detections: DetectedPerson[];
}

export interface AlertEventPayload {
  event_id: string;
  event_type: string;
  severity: AlertSeverity;
  source: string;
  message: string;
  telemetry_snapshot?: any;
  action_taken?: string;
  buzzer_activated?: boolean;
  timestamp?: number;
}

export interface ESP32Status {
  connected: boolean;
  ip?: string | null;
  connected_at_ms?: number | null;
  last_heartbeat_ms?: number | null;
  rtt_ms?: number | null;
  failsafe_active?: boolean;
  estop_active?: boolean;
  uptime_ms?: number | null;
  rssi_dbm?: number | null;
}

export interface CameraStatus {
  running: boolean;
  fps: number;
  synthetic: boolean;
  width: number;
  height: number;
  dropped_frames: number;
}

export interface TrackingStatus {
  mode: TrackingMode;
  locked: boolean;
  active_track_id?: number | null;
  tracks_count: number;
  inference_ms: number;
  fps: number;
  active_target?: ActiveTarget | null;
}

export interface SystemStatusPayload {
  timestamp: number;
  uptime_s: number;
  estop_active: boolean;
  failsafe_active?: boolean;
  esp32: ESP32Status;
  camera: CameraStatus;
  tracking: TrackingStatus;
  sensors?: Partial<SensorTelemetryPayload>;
}
