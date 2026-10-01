// Brand tokens, taken from the app so the film and the product read as one:
// seed teal from frontend/DESIGN.md, tonal containers from styles/home_landing.css.
export const C = {
  seed: '#1A6B6B',
  teal: '#0F7C77',
  tealBright: '#5EC8BE',
  ink: '#1F1F1F',
  inkSoft: '#444746',
  inkMute: '#747775',
  paper: '#FFFFFF',
  paperTint: '#F0F4F9',
  night: '#0B0F10',
  nightSoft: '#141A1B',
  container: {
    teal: '#BFECE3',
    blue: '#D3E3FD',
    green: '#C4EED0',
    yellow: '#FFE28A',
    red: '#FFDAD6',
  },
  // Google 200 tones: the deeper end of each shape's gradient, so fills read at a glance.
  deep: {
    teal: '#7FD8CC',
    blue: '#A8C7FA',
    green: '#81C995',
    yellow: '#FDD663',
    red: '#F6AEA9',
  },
  on: {
    teal: '#00201F',
    blue: '#041E49',
    green: '#072711',
    yellow: '#261A00',
    red: '#410E0B',
  },
} as const;

export type Tone = keyof typeof C.container;

export const FONT = "'Google Sans', 'Google Sans Text', system-ui, sans-serif";
export const MONO = "'Google Sans Code', ui-monospace, monospace";

export const SITE = 'open-coscientist.com';
export const REPO = 'github.com/guy915/Open-Co-Scientist';
