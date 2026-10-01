// Beat times (s) of the soundtrack: librosa's beat tracker, then each beat
// snapped to the attack of its high-frequency transient (above 2 kHz) within
// 100 ms before it, less 15 ms so an effect's onset meets the start of that
// attack rather than its peak (measured on the effects-only render). The
// tracker alone sits ~36 ms behind the attacks, enough for a cut or an effect
// to read as a slap-back after the hit; beats with no clear attack take that
// median offset. The track drifts around 94-96 bpm, so a fixed grid would land
// up to a frame off. Downbeats are every 4th from index 1, and the bass drops
// out on several of them (8.28, 10.82, 18.46, 28.64, 31.19, 38.83, 41.37 s):
// those stabs carry the film's biggest hits.
const TIMES = [
  0.045, 0.649, 1.299, 1.919, 2.569, 3.199, 3.829, 4.449, 5.079, 5.726, 6.379, 7.009, 7.639, 8.276, 8.909,
  9.549, 10.189, 10.818, 11.469, 12.093, 12.719, 13.368, 14.019, 14.644, 15.279, 15.910, 16.549, 17.179,
  17.829, 18.460, 19.109, 19.734, 20.359, 21.002, 21.659, 22.277, 22.909, 23.552, 24.189, 24.826, 25.469,
  26.094, 26.749, 27.369, 28.008, 28.642, 29.280, 29.916, 30.549, 31.185, 31.822, 32.461, 33.101, 33.738,
  34.359, 35.010, 35.639, 36.277, 36.939, 37.554, 38.192, 38.828, 39.464, 40.100, 40.732, 41.369, 42.008,
  42.646, 43.285, 43.924, 44.579, 45.196, 45.829, 46.476, 47.129, 47.759, 48.359, 49.009, 49.659, 50.309,
  50.938, 51.576, 52.219, 52.849, 53.490,
];

/**
 * Global frame of beat `i` (30 fps); fractional `i` lands between beats, e.g.
 * 2.5 is an eighth note. Beat 0 is the opening hit at 0.045 s; the film opens
 * on it, so it maps to frame 0.
 */
export const B = (i: number): number => {
  if (i === 0) return 0;
  const lo = Math.min(Math.floor(i), TIMES.length - 2);
  return Math.round((TIMES[lo] + (TIMES[lo + 1] - TIMES[lo]) * (i - lo)) * 30);
};

/** The soundtrack is 54.15 s; the film is exactly as long. */
export const LAUNCH_FRAMES = 1624;
