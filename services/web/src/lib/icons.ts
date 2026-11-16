// Inline icon set shared by Astro components and the client-rendered cards.
// Stroke icons are 24×24 on a 1.8 grid; solid icons (play/pause) opt in with `solid`.

export const ICONS: Record<string, string> = {
  home: '<path d="M3.5 10.4 12 3.6l8.5 6.8V20a1 1 0 0 1-1 1h-5v-6h-5v6h-5a1 1 0 0 1-1-1z"/>',
  compass:
    '<circle cx="12" cy="12" r="9"/><path d="m15.6 8.4-2.1 5.1-5.1 2.1 2.1-5.1z"/>',
  library:
    '<path d="M4 4v16M8.5 4v16M13 4.6l6.3 15.2M15.9 3.6l6.2 15.1"/>',
  video:
    '<rect x="2.5" y="5.5" width="14" height="13" rx="2.5"/><path d="m16.5 10 5-2.8v9.6l-5-2.8z"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  play: '<path d="M8 5.15v13.7a1 1 0 0 0 1.53.85l10.6-6.85a1 1 0 0 0 0-1.7L9.53 4.3A1 1 0 0 0 8 5.15Z"/>',
  pause:
    '<rect x="7" y="4.5" width="3.6" height="15" rx="1.2"/><rect x="13.4" y="4.5" width="3.6" height="15" rx="1.2"/>',
  'skip-back':
    '<polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5"/>',
  'skip-forward':
    '<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/>',
  shuffle:
    '<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>',
  repeat:
    '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  refresh:
    '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4.5V10H15"/>',
  'repeat-one':
    '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1.5v5"/>',
  'volume-high':
    '<path d="M4 9.5h3.2L12 5.6v12.8L7.2 14.5H4z"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6M18 6.5a7.7 7.7 0 0 1 0 11"/>',
  'volume-low':
    '<path d="M4 9.5h3.2L12 5.6v12.8L7.2 14.5H4z"/><path d="M15.5 9a4.2 4.2 0 0 1 0 6"/>',
  'volume-mute':
    '<path d="M4 9.5h3.2L12 5.6v12.8L7.2 14.5H4z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/>',
  queue:
    '<path d="M4 6h12M4 11h12M4 16h7"/><circle cx="17" cy="18" r="2.4"/><path d="M19.4 18v-7.5l3-1"/>',
  circle: '<circle cx="12" cy="12" r="9"/>',
  mic:
    '<rect x="8.5" y="2.8" width="7" height="11.4" rx="3.5"/><path d="M5.5 11.4a6.5 6.5 0 0 0 13 0M12 17.9V21M8.8 21h6.4"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  minimize: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
  more: '<circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  heart:
    '<path d="M12 20.2S3.7 15.3 3.7 9.6A4.6 4.6 0 0 1 12 6.5a4.6 4.6 0 0 1 8.3 3.1c0 5.7-8.3 10.6-8.3 10.6Z"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  'arrow-left': '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  'arrow-right': '<path d="M5 12h14M13 6l6 6-6 6"/>',
  'chevron-left': '<path d="m14.5 5-7 7 7 7"/>',
  'chevron-right': '<path d="m9.5 5 7 7-7 7"/>',
  'chevron-down': '<path d="m5 9 7 7 7-7"/>',
  'chevron-up': '<path d="m5 15 7-7 7 7"/>',
  check: '<path d="m4.5 12.5 5 5L20 6.5"/>',
  music: '<path d="M9 18V5.5l11-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  sparkles:
    '<path d="m12 3 1.7 4.8L18.5 9.5l-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  external: '<path d="M14 4h6v6M20 4l-8.5 8.5"/><path d="M18 14v5a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V7.5A1.5 1.5 0 0 1 5 6h5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3.2 2"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1.2" fill="currentColor" stroke="none"/><circle cx="3.5" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="3.5" cy="18" r="1.2" fill="currentColor" stroke="none"/>',
  trash:
    '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 13h9.4l.8-13M10 11v5.5M14 11v5.5"/>',
  link: '<path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 0 0-5.7-5.7L11.4 6.9"/><path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 0 0 5.7 5.7l1.4-1.4"/>',
  radio:
    '<circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none"/><path d="M8.6 8.6a4.8 4.8 0 0 0 0 6.8M15.4 8.6a4.8 4.8 0 0 1 0 6.8M5.8 5.8a8.8 8.8 0 0 0 0 12.4M18.2 5.8a8.8 8.8 0 0 1 0 12.4"/>',
  palette:
    '<path d="M12 3.5a8.5 8.5 0 0 0 0 17c1.4 0 2-.9 2-1.8 0-.9-.7-1.4-.7-2.4 0-1 .8-1.8 2-1.8h1.7a3.5 3.5 0 0 0 3.5-3.5c0-4.1-3.8-7.5-8.5-7.5Z"/><circle cx="8" cy="9" r="1.2" fill="currentColor" stroke="none"/><circle cx="12" cy="7" r="1.2" fill="currentColor" stroke="none"/><circle cx="16" cy="9" r="1.2" fill="currentColor" stroke="none"/><circle cx="7.5" cy="13.5" r="1.2" fill="currentColor" stroke="none"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  theater:
    '<rect x="2.5" y="4.5" width="19" height="14" rx="2.5"/><path d="M8 21h8M12 18.5V21M7.5 8.5h9M7.5 12h5"/>',
  mini: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><rect x="12" y="12" width="7.5" height="5.5" rx="1.4"/>',
  'picture-in-picture':
    '<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><rect x="12.5" y="11.5" width="7" height="6" rx="1.2"/>',
  share:
    '<circle cx="18" cy="5.5" r="2.7"/><circle cx="6" cy="12" r="2.7"/><circle cx="18" cy="18.5" r="2.7"/><path d="m8.4 10.7 7.2-3.8M8.4 13.3l7.2 3.8"/>',
  download: '<path d="M12 3.5v12M7.5 11 12 15.5 16.5 11M4.5 20.5h15"/>',
  sort: '<path d="M4 6h10M4 12h7M4 18h4M17 7v11M14 15l3 3 3-3"/>',
  verified:
    '<path d="m12 2.8 2.5 1.8 3-.2 1 2.9 2.5 1.8-1 2.9 1 2.9-2.5 1.8-1 2.9-3-.2L12 21.2l-2.5-1.8-3 .2-1-2.9L3 14.9l1-2.9-1-2.9 2.5-1.8 1-2.9 3 .2z"/><path d="m8.5 12 2.4 2.4 4.8-5"/>',
  headphones:
    '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M4 14h2.5a1 1 0 0 1 1 1v3.5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1zM20 14h-2.5a1 1 0 0 0-1 1v3.5a1 1 0 0 0 1 1H19a1 1 0 0 0 1-1z"/>',
  'wave': '<path d="M3 12h2M8 7v10M12 4v16M16 8v8M20 10v4"/>',
};

export const SOLID = new Set(['play', 'pause', 'play-fill']);

export function iconMarkup(name: string, className = '', size = 20): string {
  const body = ICONS[name] ?? ICONS.circle ?? '<circle cx="12" cy="12" r="9"/>';
  const solid = SOLID.has(name);
  return `<svg class="${className}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="${
    solid ? 'currentColor' : 'none'
  }" stroke="currentColor" stroke-width="${solid ? 0 : 1.8}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}
