// Full-screen settings page (Steam-style left menu), so options and release notes have room.
import { Field, PanelSectionRow, SidebarNavigation } from "@decky/ui";
import { MdBrightness6, MdBedtime, MdImage, MdInfoOutline, MdSystemUpdateAlt } from "react-icons/md";

import { Status } from "./api";
import {
  ArtworkRows,
  AuraRows,
  ClockRows,
  ErrorRow,
  ImageRows,
  ModeRows,
  MountingRows,
  SleepRows,
  StatusRows,
} from "./sections";
import { Faceplate, Gate, useFaceplate } from "./state";
import { Updates, UpdateRows, useUpdates } from "./updater";

export const SETTINGS_ROUTE = "/pixel-faceplate";

function Note({ text }: { text: string }) {
  return (
    <PanelSectionRow>
      <Field description={text} focusable={false} />
    </PanelSectionRow>
  );
}

function pages(f: Faceplate, status: Status, u: Updates) {
  const s = status.settings;
  const off = s.mode === "off";
  return [
    {
      title: "Display",
      icon: <MdBrightness6 />,
      content: (
        <>
          <ModeRows f={f} status={status} />
          {(s.mode === "clock" || (s.mode === "artwork" && s.artwork_idle === "clock")) && <ClockRows f={f} status={status} />}
          {s.mode === "aura" && <AuraRows f={f} status={status} />}
          {s.mode === "image" && <ImageRows f={f} status={status} />}
          <ErrorRow f={f} status={status} />
        </>
      ),
    },
    {
      title: "Game artwork",
      icon: <MdImage />,
      content:
        s.mode === "artwork" ? (
          <ArtworkRows f={f} status={status} />
        ) : (
          <Note text="These options are for the Game artwork mode. Pick it under Display to use them." />
        ),
    },
    {
      title: "Sleep and mounting",
      icon: <MdBedtime />,
      content: off ? (
        <Note text="The panel is off, so there's nothing to do at sleep or shutdown." />
      ) : (
        <>
          <SleepRows f={f} status={status} />
          <MountingRows f={f} status={status} />
        </>
      ),
    },
    {
      title: "Status",
      icon: <MdInfoOutline />,
      content: <StatusRows f={f} status={status} />,
    },
    {
      title: u.state?.available ? `Updates (${u.state.latest})` : "Updates",
      icon: <MdSystemUpdateAlt />,
      content: <UpdateRows u={u} />,
    },
  ];
}

export function SettingsPage() {
  const f = useFaceplate();
  const u = useUpdates();
  return (
    // Routes draw under Steam's top bar; this keeps the page below it.
    <div style={{ marginTop: "40px", height: "calc(100% - 40px)" }}>
      <Gate f={f}>
        {(status) => <SidebarNavigation title="Pixel Faceplate" showTitle pages={pages(f, status, u)} />}
      </Gate>
    </div>
  );
}
