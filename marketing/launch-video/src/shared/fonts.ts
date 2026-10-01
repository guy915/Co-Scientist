import {loadFont} from '@remotion/fonts';
import {staticFile} from 'remotion';

// Same Google Sans files the app ships (@fontsource/google-sans), plus Google
// Sans Code for the data callouts. loadFont blocks rendering until ready.
for (const weight of ['400', '500', '700']) {
  loadFont({
    family: 'Google Sans',
    url: staticFile(`fonts/google-sans-latin-${weight}-normal.woff2`),
    weight,
  });
}
for (const weight of ['400', '500']) {
  loadFont({
    family: 'Google Sans Code',
    url: staticFile(`fonts/google-sans-code-latin-${weight}-normal.woff2`),
    weight,
  });
}
