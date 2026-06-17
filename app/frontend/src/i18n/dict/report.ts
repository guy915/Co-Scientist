// Report tab: export/print actions, headings, empty and safety states.
import type {Bundle} from '../types';

export const report: Bundle = {
  en: {
    'report.empty': 'The report appears once the workflow finishes.',
    'report.downloadMarkdown': 'Download Markdown',
    'report.downloadJson': 'Download JSON',
    'report.copyMarkdown': 'Copy Markdown',
    'report.print': 'Print',
    'report.finalSafety': 'Final-output safety: {decision}',
  },
  he: {
    'report.empty': 'הדוח יופיע לאחר שתהליך העבודה יסתיים.',
    'report.downloadMarkdown': 'הורדת Markdown',
    'report.downloadJson': 'הורדת JSON',
    'report.copyMarkdown': 'העתקת Markdown',
    'report.print': 'הדפסה',
    'report.finalSafety': 'בטיחות הפלט הסופי: {decision}',
  },
};
