// The choices offered in the dropdowns, shared by the sidebar and the settings page.
import { ArtStyle, IdleChoice, LogoPosition, Mode, PictureSource, SleepAction } from "./api";

export const MODES: { data: Mode; label: string }[] = [
  { data: "off", label: "Off (leave panel alone)" },
  { data: "artwork", label: "Game artwork" },
  { data: "clock", label: "Clock" },
  { data: "aura", label: "Light bar aura" },
  { data: "image", label: "Custom image" },
];

export const SLEEP_ACTIONS: { data: SleepAction; label: string }[] = [
  { data: "off", label: "Turn the screen off" },
  { data: "dim", label: "Dim it" },
  { data: "keep", label: "Keep the picture" },
];

export const IDLE_CHOICES: { data: IdleChoice; label: string }[] = [
  { data: "steam", label: "Steam logo" },
  { data: "clock", label: "Clock" },
  { data: "keep", label: "Keep the last game's picture" },
  { data: "pictures", label: "Random pictures" },
];

export const PICTURE_SOURCES: { data: PictureSource; label: string }[] = [
  { data: "mix", label: "A bit of everything" },
  { data: "space", label: "Space photos (NASA)" },
  { data: "earth", label: "Whole Earth (NASA EPIC)" },
  { data: "art", label: "Paintings (Art Institute of Chicago)" },
  { data: "sky", label: "Twinkling stars" },
  { data: "cats", label: "Cats" },
];

export const ART_STYLES: { data: ArtStyle; label: string }[] = [
  { data: "logo_dim", label: "Art + logo, shaded behind logo" },
  { data: "logo", label: "Art + logo" },
  { data: "art", label: "Art only" },
  { data: "logo_only", label: "Logo only" },
];

export const LOGO_POSITIONS: { data: LogoPosition; label: string }[] = [
  { data: "top", label: "Top" },
  { data: "center", label: "Center" },
  { data: "bottom", label: "Bottom" },
];

export const PICTURE_INTERVALS = [
  { data: 1, label: "Every minute" },
  { data: 3, label: "Every 3 minutes" },
  { data: 5, label: "Every 5 minutes" },
  { data: 10, label: "Every 10 minutes" },
];

export const COLORS = [
  { data: "#ff8c14", label: "Amber" },
  { data: "#ffffff", label: "White" },
  { data: "#1a9fff", label: "Steam blue" },
  { data: "#40ff60", label: "Green" },
  { data: "#ff3050", label: "Red" },
];
