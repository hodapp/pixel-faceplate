// Typed bindings to the Python backend callables in main.py.
import { callable } from "@decky/api";

export type Mode = "off" | "artwork" | "clock" | "aura" | "image";
export type SleepAction = "off" | "dim" | "keep";
export type IdleChoice = "steam" | "clock" | "keep";

export interface Settings {
  mode: Mode;
  brightness: number;
  artwork_idle: IdleChoice;
  clock_24h: boolean;
  clock_colour: string;
  aura_interval: number;
  image_path: string;
  sleep_action: SleepAction;
  shutdown_action: SleepAction;
}

export interface Status {
  phase: "starting" | "off" | "waiting" | "running" | "asleep" | "error";
  detail: string;
  connected: boolean;
  port: string;
  uploads: number;
  lifetime_uploads: number;
  upload_ms: number;
  brightness_applied: number | null;
  appid: number;
  last_error: string;
  settings: Settings;
}

export interface SaveResult {
  ok: boolean;
  error: string;
  status: Status;
}

export const getStatus = callable<[], Status>("get_status");
export const gameEvent = callable<[appid: number, running: boolean], boolean>("game_event");
export const saveSettings = callable<[changes: Partial<Settings>], SaveResult>("save_settings");
