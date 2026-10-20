// What the panel shows when the Python side never answers, instead of Loading... forever.
import { ButtonItem, Field, Navigation, PanelSection, PanelSectionRow } from "@decky/ui";
import { useEffect, useState } from "react";

import { PLUGIN_VERSION } from "./version";

export { PLUGIN_VERSION };

export const REPO_URL = "https://github.com/hodapp/pixel-faceplate";

// get_status normally answers in well under a second. When the backend dies
// at import (Decky 3.3.0, issue #4) Decky never answers the call at all, so
// the only sign is silence.
export const STALL_MS = 10000;

interface DeckyBackendLike {
  call<Args extends unknown[], T>(route: string, ...args: Args): Promise<T>;
}

// Decky's own version, from its frontend. Not part of @decky/api, so every
// step is optional and an old or new Decky without it just gets "unknown".
export async function deckyVersion(): Promise<string> {
  const backend = (window as unknown as { DeckyBackend?: DeckyBackendLike }).DeckyBackend;
  if (!backend?.call) return "unknown";
  try {
    const info = await Promise.race([
      backend.call<[], { current?: string }>("updater/get_version_info"),
      new Promise<null>((resolve) => window.setTimeout(() => resolve(null), 3000)),
    ]);
    return info?.current || "unknown";
  } catch {
    return "unknown";
  }
}

export function useStalled(waiting: boolean): boolean {
  const [stalled, setStalled] = useState(false);
  useEffect(() => {
    if (!waiting) {
      setStalled(false);
      return;
    }
    const timer = window.setTimeout(() => setStalled(true), STALL_MS);
    return () => window.clearTimeout(timer);
  }, [waiting]);
  return stalled;
}

export function BackendNotAnswering() {
  const [decky, setDecky] = useState("checking...");
  useEffect(() => {
    let cancelled = false;
    deckyVersion().then((v) => !cancelled && setDecky(v));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <PanelSection title="Not starting">
      <PanelSectionRow>
        <Field
          label="The faceplate service didn't start"
          description={
            `Pixel Faceplate ${PLUGIN_VERSION} on Decky Loader ${decky}. ` +
            "This usually means a Decky update changed something this version relies on. " +
            "Check the releases page for a newer Pixel Faceplate. If you're already on the newest one, " +
            "open an issue with both version numbers above."
          }
          focusable={false}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => Navigation.NavigateToExternalWeb(`${REPO_URL}/releases`)}>
          Releases
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => Navigation.NavigateToExternalWeb(`${REPO_URL}/issues`)}>
          Report it
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
