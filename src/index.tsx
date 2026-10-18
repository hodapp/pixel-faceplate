// Quick Access panel for the faceplate: mode, brightness, per-mode options, live status.
import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { FileSelectionType, definePlugin, openFilePicker } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { MdGridOn } from "react-icons/md";

import {
  ArtStyle,
  GameProfile,
  IdleChoice,
  LogoPosition,
  Mode,
  PictureSource,
  SaveResult,
  Settings,
  SleepAction,
  Status,
  gameEvent,
  getStatus,
  nextPicture,
  saveGameSettings,
  saveSettings,
  writeDiagnostics,
} from "./api";

const POLL_MS = 1000;
// Brightness goes to the panel once the slider stops, not at every step.
const SLIDER_SETTLE_MS = 400;

const MODES: { data: Mode; label: string }[] = [
  { data: "off", label: "Off (leave panel alone)" },
  { data: "artwork", label: "Game artwork" },
  { data: "clock", label: "Clock" },
  { data: "aura", label: "Light bar aura" },
  { data: "image", label: "Custom image" },
];

const SLEEP_ACTIONS: { data: SleepAction; label: string }[] = [
  { data: "off", label: "Turn the screen off" },
  { data: "dim", label: "Dim it" },
  { data: "keep", label: "Keep the picture" },
];

const IDLE_CHOICES: { data: IdleChoice; label: string }[] = [
  { data: "steam", label: "Steam logo" },
  { data: "clock", label: "Clock" },
  { data: "keep", label: "Keep the last game's picture" },
  { data: "pictures", label: "Random pictures" },
];

const PICTURE_SOURCES: { data: PictureSource; label: string }[] = [
  { data: "mix", label: "A bit of everything" },
  { data: "space", label: "Space photos (NASA)" },
  { data: "earth", label: "Whole Earth (NASA EPIC)" },
  { data: "art", label: "Paintings (Art Institute of Chicago)" },
  { data: "sky", label: "Twinkling stars" },
  { data: "cats", label: "Cats" },
];

const ART_STYLES: { data: ArtStyle; label: string }[] = [
  { data: "logo_dim", label: "Art + logo, shaded behind logo" },
  { data: "logo", label: "Art + logo" },
  { data: "art", label: "Art only" },
  { data: "logo_only", label: "Logo only" },
];

const LOGO_POSITIONS: { data: LogoPosition; label: string }[] = [
  { data: "top", label: "Top" },
  { data: "center", label: "Center" },
  { data: "bottom", label: "Bottom" },
];

const PICTURE_INTERVALS = [
  { data: 1, label: "Every minute" },
  { data: 3, label: "Every 3 minutes" },
  { data: 5, label: "Every 5 minutes" },
  { data: 10, label: "Every 10 minutes" },
];

const COLORS = [
  { data: "#ff8c14", label: "Amber" },
  { data: "#ffffff", label: "White" },
  { data: "#1a9fff", label: "Steam blue" },
  { data: "#40ff60", label: "Green" },
  { data: "#ff3050", label: "Red" },
];

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  // A failed save stays on screen; the next successful poll only clears its own errors.
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [brightness, setBrightness] = useState<number | null>(null);
  const [diagnostics, setDiagnostics] = useState("");
  const brightnessTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await getStatus();
        if (!cancelled) {
          setStatus(next);
          setPollError("");
        }
      } catch (e) {
        if (!cancelled) setPollError(String(e));
      }
    };
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearTimeout(brightnessTimer.current);
    };
  }, []);

  const save = async (changes: Partial<Settings>) => {
    await apply(() => saveSettings(changes));
  };

  const saveGame = async (appid: number, changes: Partial<GameProfile> | null) => {
    await apply(() => saveGameSettings(appid, changes));
  };

  const apply = async (call: () => Promise<SaveResult>) => {
    try {
      const result = await call();
      setStatus(result.status);
      setError(result.ok ? "" : result.error);
    } catch (e) {
      setError(String(e));
    }
  };

  if (!status) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label={error || pollError ? `Backend error: ${error || pollError}` : "Loading..."} focusable={false} />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (status.handed_to) {
    return (
      <PanelSection title="Moved to GabeCubeAura">
        <PanelSectionRow>
          <Field
            label={`${status.handed_to} runs the faceplate now`}
            description={`Faceplate support is built into ${status.handed_to} now. Set it up there, then uninstall Pixel Faceplate (Decky settings > Plugins). This plugin has stopped sending anything to the panel.`}
            focusable={false}
          />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const s = status.settings;
  const appid = status.appid;
  const profile = appid ? s.game_profiles[String(appid)] : undefined;
  // What the running game shows: its own choices if it has them, else the console's.
  const art = profile ?? s;
  const saveArt = (changes: Partial<GameProfile>) => (profile ? saveGame(appid, changes) : save(changes));
  const pickImage = async () => {
    try {
      const picked = await openFilePicker(
        FileSelectionType.FILE,
        s.image_path || "/home/deck/Pictures",
        true,
        true,
        undefined,
        ["png", "jpg", "jpeg", "gif", "bmp"],
      );
      await save({ image_path: picked.realpath || picked.path, mode: "image" });
    } catch (e) {
      // Closing the picker rejects; that's not an error worth showing.
      if (String(e).trim()) setError(String(e));
    }
  };

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <DropdownItem
            label="Mode"
            rgOptions={MODES}
            selectedOption={s.mode}
            onChange={(option) => save({ mode: option.data as Mode })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label="Brightness"
            value={brightness ?? s.brightness}
            min={0}
            max={100}
            step={5}
            showValue
            onChange={(value) => {
              setBrightness(value);
              window.clearTimeout(brightnessTimer.current);
              brightnessTimer.current = window.setTimeout(() => {
                void save({ brightness: value }).finally(() => setBrightness(null));
              }, SLIDER_SETTLE_MS);
            }}
          />
        </PanelSectionRow>
        {status.brightness_applied !== null && status.brightness_applied < s.brightness && (
          <PanelSectionRow>
            <Field
              label={`Running at ${status.brightness_applied}%`}
              description="This picture is bright enough that full brightness can overload the USB port, so it's capped"
              focusable={false}
            />
          </PanelSectionRow>
        )}

        {s.mode === "artwork" && (
          <>
            {appid > 0 && (
              <PanelSectionRow>
                <ToggleField
                  label={`Just for ${gameTitle(appid)}`}
                  description={
                    profile
                      ? "Style and logo position below apply to this game only"
                      : "Off: this game uses the same style as every other game"
                  }
                  checked={Boolean(profile)}
                  onChange={(value) => saveGame(appid, value ? {} : null)}
                />
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <DropdownItem
                label="Artwork style"
                description={art.art_style === "logo_only" ? "Games without a logo show their art instead" : undefined}
                rgOptions={ART_STYLES}
                selectedOption={art.art_style}
                onChange={(option) => saveArt({ art_style: option.data as ArtStyle })}
              />
            </PanelSectionRow>
            {art.art_style !== "art" && (
              <PanelSectionRow>
                <DropdownItem
                  label="Logo position"
                  rgOptions={LOGO_POSITIONS}
                  selectedOption={art.logo_position}
                  onChange={(option) => saveArt({ logo_position: option.data as LogoPosition })}
                />
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <DropdownItem
                label="Between games"
                description={s.artwork_idle === "clock" ? "The clock writes to the panel's flash once a minute" : undefined}
                rgOptions={IDLE_CHOICES}
                selectedOption={s.artwork_idle}
                onChange={(option) => save({ artwork_idle: option.data as IdleChoice })}
              />
            </PanelSectionRow>
            {s.artwork_idle === "pictures" && (
              <>
                <PanelSectionRow>
                  <DropdownItem
                    label="Pictures of"
                    description={s.picture_source === "sky" ? "Drawn here, no network needed" : undefined}
                    rgOptions={PICTURE_SOURCES}
                    selectedOption={s.picture_source}
                    onChange={(option) => save({ picture_source: option.data as PictureSource })}
                  />
                </PanelSectionRow>
                <PanelSectionRow>
                  <DropdownItem
                    label="New picture"
                    description="Each new picture is a flash write; with no network, ones you've already seen come back"
                    rgOptions={PICTURE_INTERVALS}
                    selectedOption={s.picture_interval}
                    onChange={(option) => save({ picture_interval: option.data as number })}
                  />
                </PanelSectionRow>
                <PanelSectionRow>
                  <ButtonItem layout="below" onClick={() => nextPicture().catch((e) => setError(String(e)))}>
                    Next picture
                  </ButtonItem>
                </PanelSectionRow>
              </>
            )}
          </>
        )}

        {(s.mode === "clock" || (s.mode === "artwork" && s.artwork_idle === "clock")) && (
          <>
            <PanelSectionRow>
              <DropdownItem
                label="Clock color"
                rgOptions={COLORS}
                selectedOption={s.clock_color}
                onChange={(option) => save({ clock_color: option.data as string })}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField label="24-hour clock" checked={s.clock_24h} onChange={(value) => save({ clock_24h: value })} />
            </PanelSectionRow>
          </>
        )}

        {s.mode === "aura" && (
          <PanelSectionRow>
            <SliderField
              label="Check every (seconds)"
              description="Follows GabeCubeAura or Steam's light bar; only visible changes are sent"
              value={s.aura_interval}
              min={30}
              max={600}
              step={30}
              showValue
              onChange={(value) => save({ aura_interval: value })}
            />
          </PanelSectionRow>
        )}

        {s.mode === "image" && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={pickImage} description={s.image_path || "No image chosen"}>
              Choose image...
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      {s.mode !== "off" && (
        <PanelSection title="Mounting">
          <PanelSectionRow>
            <ToggleField
              label="Upside down (cable on the right)"
              description="Flips the picture for a faceplate mounted with its cable out the right side. The included cable won't reach; you'll need a longer one."
              checked={s.rotate}
              onChange={(value) => save({ rotate: value })}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      {s.mode !== "off" && (
        <PanelSection title="Sleep and shutdown">
          <PanelSectionRow>
            <DropdownItem
              label="When the Steam Machine sleeps"
              description="USB stays powered during sleep, so the panel stays lit unless it's told otherwise"
              rgOptions={SLEEP_ACTIONS}
              selectedOption={s.sleep_action}
              onChange={(option) => save({ sleep_action: option.data as SleepAction })}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <DropdownItem
              label="When it shuts down"
              rgOptions={SLEEP_ACTIONS}
              selectedOption={s.shutdown_action}
              onChange={(option) => save({ shutdown_action: option.data as SleepAction })}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="Status">
        <PanelSectionRow>
          <Field label={status.connected ? "Connected" : status.port ? "Not connected" : "Faceplate not found"} focusable={false}>
            {status.port}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label={status.phase.charAt(0).toUpperCase() + status.phase.slice(1)} description={status.detail} focusable={false} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
            label="Flash writes"
            description="Every picture is stored in the panel's flash. This session / all time."
            focusable={false}
          >
            {status.uploads} / {status.lifetime_uploads}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={diagnostics || "Run it while a game is running; it writes a report file to your home folder"}
            onClick={async () => {
              setDiagnostics("Writing report (takes a couple of seconds)...");
              try {
                const result = await writeDiagnostics(frontendSnapshot());
                setDiagnostics(result.ok ? `${result.summary} Saved to ${result.path}` : `Failed: ${result.error}`);
              } catch (e) {
                setDiagnostics(`Failed: ${String(e)}`);
              }
            }}
          >
            Write diagnostics report
          </ButtonItem>
        </PanelSectionRow>
        {(error || pollError || status.last_error) && (
          <PanelSectionRow>
            <Field label="Error" description={error || pollError || status.last_error} focusable={false} />
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
}

function gameTitle(appid: number): string {
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

function frontendSnapshot(): Record<string, unknown> {
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

function watchGames(): () => void {
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

export default definePlugin(() => {
  const stopWatching = watchGames();
  return {
    name: "Pixel Faceplate",
    titleView: <div className={staticClasses.Title}>Pixel Faceplate</div>,
    content: <Content />,
    icon: <MdGridOn />,
    onDismount() {
      stopWatching();
    },
  };
});
