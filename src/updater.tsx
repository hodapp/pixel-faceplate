// Updates: shows a newer GitHub release and, on a tap, hands the checked ZIP to Decky's installer.
import { ButtonItem, Field, Navigation, PanelSectionRow } from "@decky/ui";
import { useEffect, useState } from "react";

import { UpdateState, checkUpdate, prepareUpdate } from "./api";
import { REPO_URL } from "./guard";
import { PLUGIN_VERSION } from "./version";

const PLUGIN_NAME = "Pixel Faceplate";
// Decky's PluginInstallType.UPDATE: its confirm dialog says "Update".
const INSTALL_TYPE_UPDATE = 2;

interface DeckyBackendLike {
  call<Args extends unknown[], T>(route: string, ...args: Args): Promise<T>;
}

function deckyBackend(): DeckyBackendLike | null {
  const backend = (window as unknown as { DeckyBackend?: DeckyBackendLike }).DeckyBackend;
  return backend?.call ? backend : null;
}

export interface Updates {
  state: UpdateState | null;
  busy: string;
  message: string;
  check: (force: boolean) => Promise<void>;
  install: () => Promise<void>;
}

export function useUpdates(): Updates {
  const [state, setState] = useState<UpdateState | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  const check = async (force: boolean) => {
    setBusy(force ? "Checking..." : "");
    try {
      setState(await checkUpdate(force));
    } catch (e) {
      setMessage(`Couldn't check: ${String(e)}`);
    } finally {
      setBusy("");
    }
  };

  // The backend caches the answer for hours, so this is cheap to call on every open.
  useEffect(() => {
    check(false);
  }, []);

  const install = async () => {
    const backend = deckyBackend();
    if (!backend) {
      setMessage("This Decky can't install it from here. Get the ZIP from the releases page.");
      return;
    }
    setBusy("Downloading and checking...");
    setMessage("");
    try {
      const prepared = await prepareUpdate();
      if (!prepared.ok || !prepared.path || !prepared.sha256) {
        setMessage(`Update stopped: ${prepared.error}`);
        return;
      }
      // Decky asks for confirmation, checks the hash again, installs and
      // reloads us. Nothing happens unless the user says yes there too.
      await backend.call("utilities/install_plugin", prepared.path, PLUGIN_NAME, prepared.version, prepared.sha256, INSTALL_TYPE_UPDATE);
      setMessage("Confirm in Decky's dialog to install.");
      // Installing unloads us, and with us this page's route, so step off it
      // first instead of leaving the user on a blank screen. Decky's dialog
      // isn't part of this page and stays up.
      Navigation.NavigateBack();
    } catch (e) {
      setMessage(`Update stopped: ${String(e)}`);
    } finally {
      setBusy("");
    }
  };

  return { state, busy, message, check, install };
}

function summary(u: Updates): { label: string; description: string } {
  const { state } = u;
  if (!state) return { label: `Version ${PLUGIN_VERSION}`, description: u.busy || u.message || "Checking for updates..." };
  if (state.available) {
    return { label: `${state.latest} is out`, description: u.busy || u.message || `You have ${state.current}` };
  }
  return {
    label: `Version ${PLUGIN_VERSION}`,
    description: u.busy || u.message || state.error || (state.latest ? `Up to date. Latest release is ${state.latest}.` : "Up to date."),
  };
}

// Release notes are Markdown; the panel shows plain text.
function plainNotes(notes: string): string {
  return notes
    .replace(/\r/g, "")
    .replace(/^#+\s*/gm, "")
    .replace(/\*\*|__|`/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
}

// Sidebar: one line and, when there's something new, a button to the full page.
export function UpdateLine({ u, onOpen }: { u: Updates; onOpen: () => void }) {
  if (!u.state?.available) return null;
  const { label, description } = summary(u);
  return (
    <PanelSectionRow>
      <ButtonItem layout="below" description={description} onClick={onOpen}>
        {label}: update...
      </ButtonItem>
    </PanelSectionRow>
  );
}

// Settings page: the version, the update button and the release notes.
export function UpdateRows({ u }: { u: Updates }) {
  const { state } = u;
  const { label, description } = summary(u);
  const page = state?.page || `${REPO_URL}/releases`;
  return (
    <>
      <PanelSectionRow>
        <Field label={label} description={description} focusable={false} />
      </PanelSectionRow>
      {state?.available ? (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!u.busy} onClick={u.install}>
            Update to {state.latest}
          </ButtonItem>
        </PanelSectionRow>
      ) : (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!!u.busy} onClick={() => u.check(true)}>
            Check now
          </ButtonItem>
        </PanelSectionRow>
      )}
      {state?.available && state.notes && (
        <PanelSectionRow>
          {/* Focusable so the d-pad can reach it and the page scrolls to show all of it. */}
          <Field
            label={`What's new in ${state.latest}`}
            description={<div style={{ whiteSpace: "pre-wrap" }}>{plainNotes(state.notes)}</div>}
            focusable
          />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => Navigation.NavigateToExternalWeb(page)}>
          Release notes on GitHub
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}
