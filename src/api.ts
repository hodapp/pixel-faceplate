// Typed bindings to the Python backend callables in main.py.
import { callable } from "@decky/api";

export type Mode = "off" | "artwork" | "clock" | "aura" | "image";
export type SleepAction = "off" | "dim" | "keep";
export type IdleChoice = "steam" | "clock" | "keep";
export type ArtStyle = "logo_dim" | "logo" | "art" | "logo_only";
export type LogoPosition = "bottom" | "center" | "top";

export interface Settings {
  mode: Mode;
  brightness: number;
  artwork_idle: IdleChoice;
  art_style: ArtStyle;
  logo_position: LogoPosition;
  clock_24h: boolean;
  clock_color: string;
  aura_interval: number;
  image_path: string;
  sleep_action: SleepAction;
  shutdown_action: SleepAction;
  rotate: boolean;
  game_profiles: Record<string, GameProfile>;
}

export interface GameProfile {
  art_style: ArtStyle;
  logo_position: LogoPosition;
}

export interface Status {
  phase: "starting" | "off" | "waiting" | "running" | "asleep" | "busy" | "error";
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
// changes=null drops the game's own settings so it follows the console's again.
export const saveGameSettings = callable<[appid: number, changes: Partial<GameProfile> | null], SaveResult>(
  "save_game_settings",
);
