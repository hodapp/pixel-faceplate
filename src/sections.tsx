// The groups of settings, each usable in the sidebar or on the full settings page.
import { ButtonItem, DropdownItem, Field, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { FileSelectionType, openFilePicker } from "@decky/api";
import { useState } from "react";

import { ArtStyle, GameProfile, IdleChoice, LogoPosition, Mode, PictureSource, SleepAction, Status, nextPicture, writeDiagnostics } from "./api";
import {
  ART_STYLES,
  COLORS,
  IDLE_CHOICES,
  LOGO_POSITIONS,
  MODES,
  PICTURE_INTERVALS,
  PICTURE_SOURCES,
  SLEEP_ACTIONS,
} from "./options";
import { Faceplate } from "./state";
import { frontendSnapshot, gameTitle } from "./steam";

interface Props {
  f: Faceplate;
  status: Status;
}

export function ModeRows({ f, status }: Props) {
  const s = status.settings;
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Mode"
          rgOptions={MODES}
          selectedOption={s.mode}
          onChange={(option) => f.save({ mode: option.data as Mode })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label="Brightness"
          value={f.brightness ?? s.brightness}
          min={0}
          max={100}
          step={5}
          showValue
          onChange={f.setBrightness}
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
    </>
  );
}

export function NextPictureRow({ f }: { f: Faceplate }) {
  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={() => nextPicture().catch((e) => f.setError(String(e)))}>
        Next picture
      </ButtonItem>
    </PanelSectionRow>
  );
}

export function ArtworkRows({ f, status }: Props) {
  const s = status.settings;
  const appid = status.appid;
  const profile = appid ? s.game_profiles[String(appid)] : undefined;
  // What the running game shows: its own choices if it has them, else the console's.
  const art = profile ?? s;
  const saveArt = (changes: Partial<GameProfile>) => (profile ? f.saveGame(appid, changes) : f.save(changes));
  return (
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
            onChange={(value) => f.saveGame(appid, value ? {} : null)}
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
          onChange={(option) => f.save({ artwork_idle: option.data as IdleChoice })}
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
              onChange={(option) => f.save({ picture_source: option.data as PictureSource })}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <DropdownItem
              label="New picture"
              description="Each new picture is a flash write; with no network, ones you've already seen come back"
              rgOptions={PICTURE_INTERVALS}
              selectedOption={s.picture_interval}
              onChange={(option) => f.save({ picture_interval: option.data as number })}
            />
          </PanelSectionRow>
          <NextPictureRow f={f} />
        </>
      )}
    </>
  );
}

export function ClockRows({ f, status }: Props) {
  const s = status.settings;
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Clock color"
          rgOptions={COLORS}
          selectedOption={s.clock_color}
          onChange={(option) => f.save({ clock_color: option.data as string })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="24-hour clock" checked={s.clock_24h} onChange={(value) => f.save({ clock_24h: value })} />
      </PanelSectionRow>
    </>
  );
}

export function AuraRows({ f, status }: Props) {
  return (
    <PanelSectionRow>
      <SliderField
        label="Check every (seconds)"
        description="Follows GabeCubeAura or Steam's light bar; only visible changes are sent"
        value={status.settings.aura_interval}
        min={30}
        max={600}
        step={30}
        showValue
        onChange={(value) => f.save({ aura_interval: value })}
      />
    </PanelSectionRow>
  );
}

export function ImageRows({ f, status }: Props) {
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
      await f.save({ image_path: picked.realpath || picked.path, mode: "image" });
    } catch (e) {
      // Closing the picker rejects; that's not an error worth showing.
      if (String(e).trim()) f.setError(String(e));
    }
  };
  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={pickImage} description={s.image_path || "No image chosen"}>
        Choose image...
      </ButtonItem>
    </PanelSectionRow>
  );
}

export function MountingRows({ f, status }: Props) {
  return (
    <PanelSectionRow>
      <ToggleField
        label="Upside down (cable on the right)"
        description="Flips the picture for a faceplate mounted with its cable out the right side. The included cable won't reach; you'll need a longer one."
        checked={status.settings.rotate}
        onChange={(value) => f.save({ rotate: value })}
      />
    </PanelSectionRow>
  );
}

export function SleepRows({ f, status }: Props) {
  const s = status.settings;
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="When the Steam Machine sleeps"
          description="USB stays powered during sleep, so the panel stays lit unless it's told otherwise"
          rgOptions={SLEEP_ACTIONS}
          selectedOption={s.sleep_action}
          onChange={(option) => f.save({ sleep_action: option.data as SleepAction })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="When it shuts down"
          rgOptions={SLEEP_ACTIONS}
          selectedOption={s.shutdown_action}
          onChange={(option) => f.save({ shutdown_action: option.data as SleepAction })}
        />
      </PanelSectionRow>
    </>
  );
}

export function connectionLabel(status: Status): string {
  return status.connected ? "Connected" : status.port ? "Not connected" : "Faceplate not found";
}

export function phaseLabel(status: Status): string {
  return status.phase.charAt(0).toUpperCase() + status.phase.slice(1);
}

export function ErrorRow({ f, status }: Props) {
  const message = f.error || f.pollError || status.last_error;
  if (!message) return null;
  return (
    <PanelSectionRow>
      <Field label="Error" description={message} focusable={false} />
    </PanelSectionRow>
  );
}

export function StatusRows({ f, status }: Props) {
  const [diagnostics, setDiagnostics] = useState("");
  return (
    <>
      <PanelSectionRow>
        <Field label={connectionLabel(status)} focusable={false}>
          {status.port}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label={phaseLabel(status)} description={status.detail} focusable={false} />
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
      <ErrorRow f={f} status={status} />
    </>
  );
}
