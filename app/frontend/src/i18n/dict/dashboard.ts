import type {Bundle} from '../types';

export const dashboard: Bundle = {
  en: {
    'dashboard.title': 'Research runs',
    'dashboard.subtitle':
      'Hypothesis-generation workspace. Each run is durable, replayable, and reopenable.',

    // Relative time
    'dashboard.time.justNow': 'just now',
    'dashboard.time.minutesAgo': '{count}m ago',
    'dashboard.time.hoursAgo': '{count}h ago',
    'dashboard.time.daysAgo': '{count}d ago',

    // Stat cards
    'dashboard.stat.totalRuns': 'Total runs',
    'dashboard.stat.completedCount': '{count} completed',
    'dashboard.stat.inProgress': 'In progress',
    'dashboard.stat.noRunsInProgress': 'No runs in progress',
    'dashboard.stat.hypothesesGenerated': 'Hypotheses generated',
    'dashboard.stat.matchesCount': '{count} matches',
    'dashboard.stat.currentMode': 'Current mode',
    'dashboard.stat.modeMock': 'Mock',
    'dashboard.stat.modeEngine': 'Engine',
    'dashboard.stat.noLlmKey': 'No LLM key set',

    // Search
    'dashboard.search.label': 'Search by research goal',

    // Empty / error states
    'dashboard.empty.noRunsYet': 'No runs yet',
    'dashboard.empty.noRunsHint':
      'Start with a research goal to generate, debate, and rank hypotheses.',
    'dashboard.empty.createFirst': 'Create your first run',
    'dashboard.empty.noMatch': 'No runs match your filter.',

    // Table headers
    'dashboard.table.researchGoal': 'Research goal',

    // Run card / cell labels
    'dashboard.label.matches': 'Matches',
  },
  he: {
    'dashboard.title': 'ריצות מחקר',
    'dashboard.subtitle':
      'סביבת עבודה ליצירת השערות. כל ריצה נשמרת, ניתנת לשחזור ולפתיחה מחדש.',

    // Relative time
    'dashboard.time.justNow': 'הרגע',
    'dashboard.time.minutesAgo': 'לפני {count} דק׳',
    'dashboard.time.hoursAgo': 'לפני {count} שע׳',
    'dashboard.time.daysAgo': 'לפני {count} ימים',

    // Stat cards
    'dashboard.stat.totalRuns': 'סך הריצות',
    'dashboard.stat.completedCount': '{count} הושלמו',
    'dashboard.stat.inProgress': 'בתהליך',
    'dashboard.stat.noRunsInProgress': 'אין ריצות בתהליך',
    'dashboard.stat.hypothesesGenerated': 'השערות שנוצרו',
    'dashboard.stat.matchesCount': '{count} התאמות',
    'dashboard.stat.currentMode': 'מצב נוכחי',
    'dashboard.stat.modeMock': 'הדמיה',
    'dashboard.stat.modeEngine': 'מנוע',
    'dashboard.stat.noLlmKey': 'לא הוגדר מפתח LLM',

    // Search
    'dashboard.search.label': 'חיפוש לפי מטרת מחקר',

    // Empty / error states
    'dashboard.empty.noRunsYet': 'אין ריצות עדיין',
    'dashboard.empty.noRunsHint':
      'התחילו ממטרת מחקר כדי ליצור, להעמיד למבחן ולדרג השערות.',
    'dashboard.empty.createFirst': 'צרו את הריצה הראשונה שלכם',
    'dashboard.empty.noMatch': 'אין ריצות התואמות לסינון שלכם.',

    // Table headers
    'dashboard.table.researchGoal': 'מטרת מחקר',

    // Run card / cell labels
    'dashboard.label.matches': 'התאמות',
  },
};
