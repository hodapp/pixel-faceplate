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
import { useEffect, useState } from "react";
import { MdGridOn } from "react-icons/md";

import { IdleChoice, Mode, Settings, SleepAction, Status, gameEvent, getStatus, saveSettings } from "./api";

const POLL_MS = 1000;

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
];

const COLOURS = [
  { data: "#ff8c14", label: "Amber" },
  { data: "#ffffff", label: "White" },
  { data: "#1a9fff", label: "Steam blue" },
  { data: "#40ff60", label: "Green" },
  { data: "#ff3050", label: "Red" },
];

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await getStatus();
        if (!cancelled) {
          setStatus(next);
          setError("");
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    };
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const save = async (changes: Partial<Settings>) => {
    try {
      const result = await saveSettings(changes);
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
          <Field label={error ? `Backend error: ${error}` : "Loading..."} focusable={false} />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const s = status.settings;
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
            value={s.brightness}
            min={0}
            max={100}
            step={5}
            showValue
            onChange={(value) => save({ brightness: value })}
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
            <PanelSectionRow>
              <DropdownItem
                label="Between games"
                description={s.artwork_idle === "clock" ? "The clock writes to the panel's flash once a minute" : undefined}
                rgOptions={IDLE_CHOICES}
                selectedOption={s.artwork_idle}
                onChange={(option) => save({ artwork_idle: option.data as IdleChoice })}
              />
            </PanelSectionRow>
          </>
        )}

        {(s.mode === "clock" || (s.mode === "artwork" && s.artwork_idle === "clock")) && (
          <>
            <PanelSectionRow>
              <DropdownItem
                label="Clock colour"
                rgOptions={COLOURS}
                selectedOption={s.clock_colour}
                onChange={(option) => save({ clock_colour: option.data as string })}
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
        {(error || status.last_error) && (
          <PanelSectionRow>
            <Field label="Error" description={error || status.last_error} focusable={false} />
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
}

// Steam's launch/exit events, the same hook GabeCubeAura uses. The backend
// also checks /proc, so a client without this hook still works.
interface LifetimeEvent {
  unAppID?: number;
  bRunning?: boolean;
}

function watchGames(): () => void {
  try {
    const sessions = (window as unknown as {
      SteamClient?: { GameSessions?: { RegisterForAppLifetimeNotifications?: (cb: (e: LifetimeEvent) => void) => { unregister?: () => void } } };
    }).SteamClient?.GameSessions;
    const registration = sessions?.RegisterForAppLifetimeNotifications?.((event) => {
      const appid = Number(event?.unAppID) >>> 0;
      if (appid) gameEvent(appid, Boolean(event?.bRunning)).catch(() => undefined);
    });
    return () => registration?.unregister?.();
  } catch {
    return () => undefined;
  }
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
