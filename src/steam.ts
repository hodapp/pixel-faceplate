// What Steam's UI says about the running game: launch/exit events, names, the diagnostics snapshot.
import { gameEvent } from "./api";

export function gameTitle(appid: number): string {
  const store = (window as unknown as {
    appStore?: { GetAppOverviewByAppID?: (id: number) => { display_name?: string } | null };
  }).appStore;
  try {
    return store?.GetAppOverviewByAppID?.(appid)?.display_name || "this game";
  } catch {
    return "this game";
  }
}

// Steam's launch/exit events, the same hook GabeCubeAura uses. The backend
// also checks /proc, so a client without this hook still works.
interface LifetimeEvent {
  unAppID?: number;
  bRunning?: boolean;
}

// How often the running game is re-read from Steam's UI store (JS only, no panel traffic).
const RUNNING_POLL_MS = 2000;

// Steam's own idea of the game in front: also right for non-Steam games
// (shortcuts), whose launch events don't always carry a usable app ID.
function runningAppId(): number {
  try {
    const store = (window as unknown as {
      SteamUIStore?: { MainRunningApp?: { appid?: number | string } | null };
    }).SteamUIStore;
    const id = Number(store?.MainRunningApp?.appid);
    return Number.isFinite(id) && id > 0 ? id >>> 0 : 0;
  } catch {
    return 0;
  }
}

// The last few launch/exit events, for the diagnostics report.
const recentEvents: { at: string; appid: number; running: boolean; from: string }[] = [];

function logEvent(appid: number, running: boolean, from: string) {
  recentEvents.push({ at: new Date().toISOString(), appid, running, from });
  if (recentEvents.length > 10) recentEvents.shift();
}

export function frontendSnapshot(): Record<string, unknown> {
  let app: Record<string, unknown> = {};
  try {
    const main = (window as unknown as { SteamUIStore?: { MainRunningApp?: Record<string, unknown> | null } })
      .SteamUIStore?.MainRunningApp;
    if (main) {
      for (const key of ["appid", "gameid", "display_name", "app_type", "local_per_client_data"]) {
        const value = main[key];
        app[key] = typeof value === "object" ? String(value) : value;
      }
    } else {
      app = { none: true };
    }
  } catch (e) {
    app = { error: String(e) };
  }
  return { main_running_appid: runningAppId(), main_running_app: app, recent_events: recentEvents };
}

export function watchGames(): () => void {
  let registration: { unregister?: () => void } | undefined;
  try {
    const sessions = (window as unknown as {
      SteamClient?: { GameSessions?: { RegisterForAppLifetimeNotifications?: (cb: (e: LifetimeEvent) => void) => { unregister?: () => void } } };
    }).SteamClient?.GameSessions;
    registration = sessions?.RegisterForAppLifetimeNotifications?.((event) => {
      const appid = Number(event?.unAppID) >>> 0;
      logEvent(appid, Boolean(event?.bRunning), "lifetime event");
      if (appid) gameEvent(appid, Boolean(event?.bRunning)).catch(() => undefined);
      if (event?.bRunning) {
        // If the event's ID isn't the one Steam's UI settles on (with
        // shortcuts, possibly), Steam's wins once it's there.
        window.setTimeout(() => {
          const settled = runningAppId();
          if (settled && settled !== appid) gameEvent(settled, true).catch(() => undefined);
        }, RUNNING_POLL_MS);
      }
    });
  } catch {
    registration = undefined;
  }
  // Report changes in Steam's running game too; this is what catches shortcuts.
  let last = runningAppId();
  if (last) gameEvent(last, true).catch(() => undefined);
  const timer = window.setInterval(() => {
    const now = runningAppId();
    if (now === last) return;
    logEvent(now, Boolean(now), "SteamUIStore");
    if (last) gameEvent(last, false).catch(() => undefined);
    if (now) gameEvent(now, true).catch(() => undefined);
    last = now;
  }, RUNNING_POLL_MS);
  return () => {
    window.clearInterval(timer);
    try {
      registration?.unregister?.();
    } catch {
      // Steam already dropped it
    }
  };
}
