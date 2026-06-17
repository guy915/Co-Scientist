import type {Bundle} from '../types';

export const runDetail: Bundle = {
  en: {
    // Document titles (used by NoIndex on the run routes).
    'runDetail.title.runs': 'Research runs',
    'runDetail.title.new': 'New research run',
    'runDetail.title.run': 'Research run',
    // Tab navigation labels.
    'runDetail.tab.overview': 'Overview',
    'runDetail.tab.ideas': 'Ideas',
    'runDetail.tab.evidence': 'Evidence',
    'runDetail.tab.tournament': 'Tournament',
    'runDetail.tab.report': 'Report',
    'runDetail.tab.chat': 'Chat',
    // Run header.
    'runDetail.header.allRuns': 'All runs',
    'runDetail.header.live': 'live',
    'runDetail.action.refresh': 'Refresh',
    'runDetail.action.exportReport': 'Export Report',
    // Toasts.
    'runDetail.toast.completed': 'Run completed.',
    'runDetail.toast.failed': 'Run {status}',
    'runDetail.toast.failedWithError': 'Run {status}: {error}',
    // Status pill (safety-specific label not in common).
    'runDetail.status.blockedSafety': 'Blocked (safety)',
    // Mock banner.
    'runDetail.banner.liveMode': 'Live engine mode',
    'runDetail.banner.provider': 'provider:',
    'runDetail.banner.model': 'model:',
    'runDetail.banner.mockTitle': 'Mock Mode',
    'runDetail.banner.mockBody':
      ' — no LLM provider key detected. The workflow runs deterministic offline data so the full UI surface is exercisable. Set ',
    'runDetail.banner.mockBodyEnd': ' in ',
    'runDetail.banner.mockBodyTail': ' to use the real engine.',
  },
  he: {
    'runDetail.title.runs': 'ריצות מחקר',
    'runDetail.title.new': 'ריצת מחקר חדשה',
    'runDetail.title.run': 'ריצת מחקר',
    // Tab navigation labels.
    'runDetail.tab.overview': 'סקירה',
    'runDetail.tab.ideas': 'רעיונות',
    'runDetail.tab.evidence': 'ראיות',
    'runDetail.tab.tournament': 'טורניר',
    'runDetail.tab.report': 'דוח',
    'runDetail.tab.chat': 'צ׳אט',
    // Run header.
    'runDetail.header.allRuns': 'כל הריצות',
    'runDetail.header.live': 'חי',
    'runDetail.action.refresh': 'רענון',
    'runDetail.action.exportReport': 'ייצוא דוח',
    // Toasts.
    'runDetail.toast.completed': 'הריצה הושלמה.',
    'runDetail.toast.failed': 'הריצה {status}',
    'runDetail.toast.failedWithError': 'הריצה {status}: {error}',
    // Status pill (safety-specific label not in common).
    'runDetail.status.blockedSafety': 'חסומה (בטיחות)',
    // Mock banner.
    'runDetail.banner.liveMode': 'מצב מנוע חי',
    'runDetail.banner.provider': 'ספק:',
    'runDetail.banner.model': 'מודל:',
    'runDetail.banner.mockTitle': 'מצב הדמיה',
    'runDetail.banner.mockBody':
      ' — לא זוהה מפתח ספק LLM. תהליך העבודה מריץ נתונים דטרמיניסטיים במצב לא מקוון כדי שכל ממשק המשתמש יהיה ניתן להפעלה. הגדירו ',
    'runDetail.banner.mockBodyEnd': ' בקובץ ',
    'runDetail.banner.mockBodyTail': ' כדי להשתמש במנוע האמיתי.',
  },
};
