// Live status and saving, shared by the sidebar and the settings page, plus what to show before there's a status.
import { Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { ReactNode, useEffect, useRef, useState } from "react";

import { GameProfile, SaveResult, Settings, Status, getStatus, saveGameSettings, saveSettings } from "./api";
import { BackendNotAnswering, useStalled } from "./guard";

const POLL_MS = 1000;
// Brightness goes to the panel once the slider stops, not at every step.
const SLIDER_SETTLE_MS = 400;

export interface Faceplate {
  status: Status | null;
  // A failed save stays on screen; the next successful poll only clears its own errors.
  error: string;
  pollError: string;
  stalled: boolean;
  setError: (message: string) => void;
  save: (changes: Partial<Settings>) => Promise<void>;
  saveGame: (appid: number, changes: Partial<GameProfile> | null) => Promise<void>;
  // The slider's value while it moves, before the save lands.
  brightness: number | null;
  setBrightness: (value: number) => void;
}

export function useFaceplate(): Faceplate {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [brightness, setBrightnessLive] = useState<number | null>(null);
  const brightnessTimer = useRef<number | undefined>(undefined);
  const stalled = useStalled(status === null);

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

  const apply = async (call: () => Promise<SaveResult>) => {
    try {
      const result = await call();
      setStatus(result.status);
      setError(result.ok ? "" : result.error);
    } catch (e) {
      setError(String(e));
    }
  };

  const save = (changes: Partial<Settings>) => apply(() => saveSettings(changes));
  const saveGame = (appid: number, changes: Partial<GameProfile> | null) => apply(() => saveGameSettings(appid, changes));

  const setBrightness = (value: number) => {
    setBrightnessLive(value);
    window.clearTimeout(brightnessTimer.current);
    brightnessTimer.current = window.setTimeout(() => {
      void save({ brightness: value }).finally(() => setBrightnessLive(null));
    }, SLIDER_SETTLE_MS);
  };

  return { status, error, pollError, stalled, setError, save, saveGame, brightness, setBrightness };
}

// Renders children only once there's a status to show and nobody else drives the panel.
export function Gate({ f, children }: { f: Faceplate; children: (status: Status) => ReactNode }) {
  const { status, error, pollError, stalled } = f;
  if (!status && stalled && !error && !pollError) {
    return <BackendNotAnswering />;
  }
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
  return <>{children(status)}</>;
}
