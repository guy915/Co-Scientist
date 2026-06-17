// Public marketing pages: landing, demo, and 404.
import type {Bundle} from '../types';

export const landing: Bundle = {
  en: {
    // Landing — SEO
    'landing.seo.description':
      'An AI-powered assistant for scientific discovery. Generates hypotheses, debates approaches, and proposes solutions – grounded in literature.',

    // Landing — hero
    'landing.hero.subhead':
      'Accelerating scientific discovery with AI-driven collaboration.',
    'landing.hero.openWorkbench': 'Open the workbench',
    'landing.hero.exploreDemo': 'Explore a demo',
    'landing.hero.previewAria': 'Example Co-Scientist workbench result',

    // Landing — workflow
    'landing.workflow.title': 'From question to research direction',
    'landing.workflow.subtitle':
      'A structured multi-agent workflow keeps the reasoning inspectable at every stage.',
    'landing.workflow.scope.title': 'Scope',
    'landing.workflow.scope.description':
      'Clarify the research goal and plan the investigation.',
    'landing.workflow.evidence.title': 'Evidence',
    'landing.workflow.evidence.description':
      'Retrieve literature and inspect supporting context.',
    'landing.workflow.generate.title': 'Generate',
    'landing.workflow.generate.description':
      'Produce distinct, testable candidate hypotheses.',
    'landing.workflow.debate.title': 'Debate',
    'landing.workflow.debate.description':
      'Review, compare, and rank ideas through pairwise critique.',
    'landing.workflow.synthesize.title': 'Synthesize',
    'landing.workflow.synthesize.description':
      'Assemble the strongest reasoning into a research report.',

    // Landing — featured demo
    'landing.featured.label': 'Completed research demo',
    'landing.featured.readDemo': 'Read the completed demo',
    'landing.featured.leadingHypothesis': 'Leading hypothesis',
    'landing.featured.completed': 'Completed',

    // Landing — research note
    'landing.research.label': 'Built from published research',
    'landing.research.title':
      'An open implementation of a multi-agent research workflow.',
    'landing.research.body1':
      'Co-Scientist is an independent open-source implementation inspired by published Google DeepMind research on AI co-scientist systems.',
    'landing.research.body2':
      'This project is not affiliated with, endorsed by, or an official product of Google or Google DeepMind.',
    'landing.research.readResearch': 'Read the published research',

    // Landing — CTA
    'landing.cta.title': 'Start with a research question.',
    'landing.cta.subtitle':
      'Generate, challenge, and refine hypotheses in the workbench.',
    'landing.cta.startRun': 'Start a research run',
    'landing.cta.viewGithub': 'View on GitHub',

    // Landing — workbench preview
    'landing.preview.researchGoal': 'Research goal',
    'landing.preview.goalText':
      'How could ferroptosis modulation improve chemotherapy response?',
    'landing.preview.completed': 'Completed',
    'landing.preview.progressAria': 'Research workflow progress',
    'landing.preview.rankedHypotheses': 'Ranked hypotheses',
    'landing.preview.score': 'Score',
    'landing.preview.rank1.title':
      'Coordinate redox and lipid-peroxidation control',
    'landing.preview.rank1.meta': 'High testability · 4 evidence links',
    'landing.preview.rank2.title':
      'Target a rate-limiting metabolic dependency',
    'landing.preview.rank2.meta': 'High novelty · 3 evidence links',
    'landing.preview.rank3.title': 'Sequence sensitization before chemotherapy',
    'landing.preview.rank3.meta': 'Moderate evidence · 3 evidence links',
    'landing.preview.footer.hypotheses': '10 hypotheses',
    'landing.preview.footer.debates': '12 debates',
    'landing.preview.footer.evidence': '4 evidence records',

    // Demo page
    'landing.demo.backLink': 'Co-Scientist home',
    'landing.demo.label': 'Completed research demo',
    'landing.demo.completed': 'Completed',
    'landing.demo.researchGoal': 'Research goal',
    'landing.demo.featuredHypotheses': 'Featured hypotheses',
    'landing.demo.featuredSubtitle':
      'Illustrative candidates surfaced and ranked by the seeded demonstration.',
    'landing.demo.evidenceLabel': 'Evidence and limitations',
    'landing.demo.evidenceTitle': 'A transparent product demonstration.',
    'landing.demo.inspectTitle': 'Inspect the full workbench view',
    'landing.demo.inspectSubtitle':
      'Open the generated ideas, evidence, tournament, and synthesis report.',
    'landing.demo.openThisDemo': 'Open this demo',
    'landing.demo.openWorkbench': 'Open the workbench',
    'landing.demo.startNewRun': 'Start a new run',

    // 404
    'landing.notFound.seoTitle': 'Page not found - Co-Scientist',
    'landing.notFound.seoDescription': 'The page you requested does not exist.',
    'landing.notFound.code': '404',
    'landing.notFound.title': 'Page not found',
    'landing.notFound.body': 'The page you requested does not exist.',
    'landing.notFound.returnHome': 'Return home',
    'landing.notFound.openWorkbench': 'Open the workbench',
  },
  he: {
    // Landing — SEO
    'landing.seo.description':
      'עוזר מבוסס בינה מלאכותית לתגליות מדעיות. מייצר השערות, דן בגישות ומציע פתרונות – מבוסס על ספרות מחקרית.',

    // Landing — hero
    'landing.hero.subhead':
      'מאיצים תגליות מדעיות באמצעות שיתוף פעולה מבוסס בינה מלאכותית.',
    'landing.hero.openWorkbench': 'פתחו את סביבת העבודה',
    'landing.hero.exploreDemo': 'חקרו הדגמה',
    'landing.hero.previewAria': 'דוגמה לתוצאה בסביבת העבודה של Co-Scientist',

    // Landing — workflow
    'landing.workflow.title': 'משאלה לכיוון מחקר',
    'landing.workflow.subtitle':
      'תהליך עבודה מובנה מרובה-סוכנים שומר על שקיפות ההיגיון בכל שלב.',
    'landing.workflow.scope.title': 'הגדרה',
    'landing.workflow.scope.description':
      'בהירו את מטרת המחקר ותכננו את החקירה.',
    'landing.workflow.evidence.title': 'ראיות',
    'landing.workflow.evidence.description':
      'אחזרו ספרות מחקרית ובחנו הקשר תומך.',
    'landing.workflow.generate.title': 'יצירה',
    'landing.workflow.generate.description':
      'הפיקו השערות מועמדות נבדלות הניתנות לבדיקה.',
    'landing.workflow.debate.title': 'דיון',
    'landing.workflow.debate.description':
      'סקרו, השוו ודרגו רעיונות באמצעות ביקורת זוגית.',
    'landing.workflow.synthesize.title': 'סינתזה',
    'landing.workflow.synthesize.description':
      'הרכיבו את ההיגיון החזק ביותר לכדי דוח מחקרי.',

    // Landing — featured demo
    'landing.featured.label': 'הדגמת מחקר שהושלמה',
    'landing.featured.readDemo': 'קראו את ההדגמה שהושלמה',
    'landing.featured.leadingHypothesis': 'השערה מובילה',
    'landing.featured.completed': 'הושלם',

    // Landing — research note
    'landing.research.label': 'נבנה על בסיס מחקר שפורסם',
    'landing.research.title': 'יישום פתוח של תהליך מחקר מרובה-סוכנים.',
    'landing.research.body1':
      'Co-Scientist הוא יישום עצמאי בקוד פתוח בהשראת מחקר שפורסם על ידי Google DeepMind בנושא מערכות AI co-scientist.',
    'landing.research.body2':
      'פרויקט זה אינו מסונף, מאושר או מהווה מוצר רשמי של Google או Google DeepMind.',
    'landing.research.readResearch': 'קראו את המחקר שפורסם',

    // Landing — CTA
    'landing.cta.title': 'התחילו עם שאלת מחקר.',
    'landing.cta.subtitle': 'ייצרו, אתגרו וזקקו השערות בסביבת העבודה.',
    'landing.cta.startRun': 'התחילו ריצת מחקר',
    'landing.cta.viewGithub': 'צפו ב-GitHub',

    // Landing — workbench preview
    'landing.preview.researchGoal': 'מטרת מחקר',
    'landing.preview.goalText':
      'כיצד ויסות פרופטוזיס יכול לשפר את התגובה לכימותרפיה?',
    'landing.preview.completed': 'הושלם',
    'landing.preview.progressAria': 'התקדמות תהליך המחקר',
    'landing.preview.rankedHypotheses': 'השערות מדורגות',
    'landing.preview.score': 'ציון',
    'landing.preview.rank1.title': 'תיאום בקרת חמצון-חיזור וחמצון שומנים',
    'landing.preview.rank1.meta': 'ניתנות גבוהה לבדיקה · 4 קישורי ראיות',
    'landing.preview.rank2.title': 'מיקוד בתלות מטבולית מגבילת-קצב',
    'landing.preview.rank2.meta': 'חדשנות גבוהה · 3 קישורי ראיות',
    'landing.preview.rank3.title': 'תזמון רגישות לפני כימותרפיה',
    'landing.preview.rank3.meta': 'ראיות בינוניות · 3 קישורי ראיות',
    'landing.preview.footer.hypotheses': '10 השערות',
    'landing.preview.footer.debates': '12 דיונים',
    'landing.preview.footer.evidence': '4 רשומות ראיות',

    // Demo page
    'landing.demo.backLink': 'דף הבית של Co-Scientist',
    'landing.demo.label': 'הדגמת מחקר שהושלמה',
    'landing.demo.completed': 'הושלם',
    'landing.demo.researchGoal': 'מטרת מחקר',
    'landing.demo.featuredHypotheses': 'השערות נבחרות',
    'landing.demo.featuredSubtitle':
      'מועמדות להמחשה שעלו ודורגו על ידי ההדגמה המוכנה.',
    'landing.demo.evidenceLabel': 'ראיות ומגבלות',
    'landing.demo.evidenceTitle': 'הדגמת מוצר שקופה.',
    'landing.demo.inspectTitle': 'בחנו את התצוגה המלאה של סביבת העבודה',
    'landing.demo.inspectSubtitle':
      'פתחו את הרעיונות שנוצרו, הראיות, הטורניר ודוח הסינתזה.',
    'landing.demo.openThisDemo': 'פתחו הדגמה זו',
    'landing.demo.openWorkbench': 'פתחו את סביבת העבודה',
    'landing.demo.startNewRun': 'התחילו ריצה חדשה',

    // 404
    'landing.notFound.seoTitle': 'הדף לא נמצא - Co-Scientist',
    'landing.notFound.seoDescription': 'הדף שביקשתם אינו קיים.',
    'landing.notFound.code': '404',
    'landing.notFound.title': 'הדף לא נמצא',
    'landing.notFound.body': 'הדף שביקשתם אינו קיים.',
    'landing.notFound.returnHome': 'חזרה לדף הבית',
    'landing.notFound.openWorkbench': 'פתחו את סביבת העבודה',
  },
};
