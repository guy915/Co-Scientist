// Merges every translation namespace into a single per-locale message map.
//
// Each file under `dict/` exports a `Bundle` (the same keys translated per
// locale). Keys are namespaced strings like `dashboard.title`; namespaces never
// overlap, so a flat spread is a safe merge. Add a new area by creating its
// dict file and listing it here.
import type {Bundle, Locale, Messages} from './types';
import {LOCALES} from './types';

import {common} from './dict/common';
import {landing} from './dict/landing';
import {dashboard} from './dict/dashboard';
import {newRun} from './dict/newRun';
import {runDetail} from './dict/runDetail';
import {overview} from './dict/overview';
import {ideas} from './dict/ideas';
import {evidence} from './dict/evidence';
import {tournament} from './dict/tournament';
import {report} from './dict/report';
import {chat} from './dict/chat';
import {misc} from './dict/misc';

const BUNDLES: Bundle[] = [
  common,
  landing,
  dashboard,
  newRun,
  runDetail,
  overview,
  ideas,
  evidence,
  tournament,
  report,
  chat,
  misc,
];

function mergeLocale(locale: Locale): Messages {
  const out: Messages = {};
  for (const bundle of BUNDLES) {
    Object.assign(out, bundle[locale]);
  }
  return out;
}

/** The fully merged message map for every supported locale. */
export const MESSAGES: Record<Locale, Messages> = LOCALES.reduce(
  (acc, locale) => {
    acc[locale] = mergeLocale(locale);
    return acc;
  },
  {} as Record<Locale, Messages>,
);
