// Quick Access panel (mode, brightness, status at a glance) and the plugin's entry point.
import { ButtonItem, Field, Navigation, PanelSection, PanelSectionRow, staticClasses } from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { MdGridOn } from "react-icons/md";

import { SETTINGS_ROUTE, SettingsPage } from "./page";
import { ErrorRow, ModeRows, NextPictureRow, connectionLabel, phaseLabel } from "./sections";
import { Gate, useFaceplate } from "./state";
import { watchGames } from "./steam";
import { UpdateLine, useUpdates } from "./updater";

function openSettings() {
  Navigation.Navigate(SETTINGS_ROUTE);
  Navigation.CloseSideMenus();
}

function Content() {
  const f = useFaceplate();
  const u = useUpdates();
  return (
    <Gate f={f}>
      {(status) => (
        <PanelSection>
          <ModeRows f={f} status={status} />
          {status.settings.mode === "artwork" && status.settings.artwork_idle === "pictures" && !status.appid && (
            <NextPictureRow f={f} />
          )}
          <PanelSectionRow>
            <Field label={connectionLabel(status)} description={`${phaseLabel(status)}: ${status.detail}`} focusable={false} />
          </PanelSectionRow>
          <ErrorRow f={f} status={status} />
          <UpdateLine u={u} onOpen={openSettings} />
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={openSettings}>
              Settings
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
    </Gate>
  );
}

export default definePlugin(() => {
  const stopWatching = watchGames();
  routerHook.addRoute(SETTINGS_ROUTE, SettingsPage, { exact: true });
  return {
    name: "Pixel Faceplate",
    titleView: <div className={staticClasses.Title}>Pixel Faceplate</div>,
    content: <Content />,
    icon: <MdGridOn />,
    onDismount() {
      stopWatching();
      routerHook.removeRoute(SETTINGS_ROUTE);
    },
  };
});
