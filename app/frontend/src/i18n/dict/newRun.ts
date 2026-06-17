import type {Bundle} from '../types';

export const newRun: Bundle = {
  en: {
    'newRun.title': 'New research run',
    'newRun.subtitle':
      'Frame a research goal. The supervisor will scope it, retrieve evidence, generate candidate hypotheses, debate them in an Elo tournament, and synthesize a report.',
    'newRun.goal.label': 'Research goal',
    'newRun.goal.placeholder':
      'Investigate the mechanism of glucose homeostasis under cold stress…',
    'newRun.goal.required': 'Provide a research goal.',
    'newRun.suggested.heading': 'Try a suggested research goal:',
    'newRun.suggested.1':
      'Identify novel mechanisms of selective autophagy in aging neural tissue.',
    'newRun.suggested.2':
      'Propose drug repurposing candidates for triple-negative breast cancer that act through mitochondrial biogenesis.',
    'newRun.suggested.3':
      'Investigate how cold-stress reshapes glucose homeostasis via brown adipose signalling.',
    'newRun.profile.legend': 'Profile',
    'newRun.profile.standard.desc':
      'Fast scoping. 5 hypotheses, evolve all, 1 iteration, ~10 min.',
    'newRun.profile.advanced.desc':
      'Deeper run. 8 hypotheses, evolve all, 2 iterations, ~25 min.',
    'newRun.overrides.summary': 'Configuration overrides',
    'newRun.overrides.initial': 'Initial hypotheses',
    'newRun.overrides.maxIters': 'Max iterations',
    'newRun.overrides.evolution': 'Evolution top-k',
  },
  he: {
    'newRun.title': 'ריצת מחקר חדשה',
    'newRun.subtitle':
      'נסחו מטרת מחקר. המפקח יתחם אותה, יאסוף ראיות, ייצר השערות מועמדות, יעמת ביניהן בטורניר Elo ויסכם דוח.',
    'newRun.goal.label': 'מטרת מחקר',
    'newRun.goal.placeholder':
      'חקרו את מנגנון שיווי המשקל של הגלוקוז בתנאי עקת קור…',
    'newRun.goal.required': 'יש לספק מטרת מחקר.',
    'newRun.suggested.heading': 'נסו מטרת מחקר מוצעת:',
    'newRun.suggested.1':
      'זהו מנגנונים חדשים של אוטופגיה סלקטיבית ברקמה עצבית מזדקנת.',
    'newRun.suggested.2':
      'הציעו מועמדים למיקום מחדש של תרופות לסרטן שד משולש-שלילי הפועלים דרך ייצור מיטוכונדריה.',
    'newRun.suggested.3':
      'חקרו כיצד עקת קור מעצבת מחדש את שיווי המשקל של הגלוקוז דרך איתות רקמת שומן חום.',
    'newRun.profile.legend': 'פרופיל',
    'newRun.profile.standard.desc':
      'תיחום מהיר. 5 השערות, אבולוציה של כולן, איטרציה אחת, כ-10 דקות.',
    'newRun.profile.advanced.desc':
      'ריצה מעמיקה. 8 השערות, אבולוציה של כולן, 2 איטרציות, כ-25 דקות.',
    'newRun.overrides.summary': 'עקיפת הגדרות',
    'newRun.overrides.initial': 'השערות התחלתיות',
    'newRun.overrides.maxIters': 'מספר איטרציות מרבי',
    'newRun.overrides.evolution': 'אבולוציה top-k',
  },
};
