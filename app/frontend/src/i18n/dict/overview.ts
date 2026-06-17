import type {Bundle} from '../types';

export const overview: Bundle = {
  en: {
    // Stat labels (label.hypotheses / label.evidence / label.elo live in common)
    'overview.stat.topElo': 'Top Elo',
    'overview.stat.evidenceSources': 'Evidence sources',
    'overview.stat.pipelineEvents': 'Pipeline events',
    'overview.stat.hypothesesSub': '{initial} initial · {evolved} evolved',
    'overview.stat.topEloSub': 'from {matches} matches',
    'overview.stat.eventsSub': '{events} persisted',

    // Sections
    'overview.section.timeline': 'Pipeline timeline',
    'overview.section.safety': 'Safety decisions',
    'overview.timeline.waiting': 'Waiting for events…',

    // Agent labels (keyed by AGENT_LABELS map key)
    'overview.agent.supervisor.plan': 'Supervisor',
    'overview.agent.intake.scope': 'Intake',
    'overview.agent.safety.intake': 'Safety (intake)',
    'overview.agent.literature_review': 'Literature retrieval',
    'overview.agent.generate': 'Generation',
    'overview.agent.reflection': 'Reflection',
    'overview.agent.proximity': 'Proximity',
    'overview.agent.ranking': 'Ranking',
    'overview.agent.evolve': 'Evolution',
    'overview.agent.meta_review': 'Meta-review',
    'overview.agent.citation_audit': 'Citation audit',
    'overview.agent.safety.final': 'Safety (final)',
    'overview.agent.report': 'Report synthesis',
    'overview.agent.status': 'Status',
    'overview.agent.lifecycle': 'Lifecycle',

    // Event payload summaries
    'overview.event.generate': '{n} initial hypotheses',
    'overview.event.evolve': '{n} evolved children',
    'overview.event.ranking': 'iter {iteration} · {n} matches',
    'overview.event.literature_review': '{n} sources',
    'overview.event.citation_audit':
      '{verified} verified · {partial} partial · {unsupported} unsupported · {unavailable} unavailable',
    'overview.event.report': 'report saved',
    'overview.event.meta_review': 'iter {iteration} critique',
    'overview.event.supervisor.plan': 'plan with {n} agents',
  },
  he: {
    // Stat labels
    'overview.stat.topElo': 'Elo מוביל',
    'overview.stat.evidenceSources': 'מקורות ראיות',
    'overview.stat.pipelineEvents': 'אירועי צנרת',
    'overview.stat.hypothesesSub': '{initial} ראשוניות · {evolved} מפותחות',
    'overview.stat.topEloSub': 'מתוך {matches} עימותים',
    'overview.stat.eventsSub': '{events} נשמרו',

    // Sections
    'overview.section.timeline': 'ציר הזמן של הצנרת',
    'overview.section.safety': 'החלטות בטיחות',
    'overview.timeline.waiting': 'ממתין לאירועים…',

    // Agent labels
    'overview.agent.supervisor.plan': 'מנהל',
    'overview.agent.intake.scope': 'קליטה',
    'overview.agent.safety.intake': 'בטיחות (קליטה)',
    'overview.agent.literature_review': 'אחזור ספרות',
    'overview.agent.generate': 'יצירה',
    'overview.agent.reflection': 'רפלקציה',
    'overview.agent.proximity': 'קרבה',
    'overview.agent.ranking': 'דירוג',
    'overview.agent.evolve': 'אבולוציה',
    'overview.agent.meta_review': 'מטא-סקירה',
    'overview.agent.citation_audit': 'ביקורת ציטוטים',
    'overview.agent.safety.final': 'בטיחות (סופית)',
    'overview.agent.report': 'סינתזת דוח',
    'overview.agent.status': 'סטטוס',
    'overview.agent.lifecycle': 'מחזור חיים',

    // Event payload summaries
    'overview.event.generate': '{n} השערות ראשוניות',
    'overview.event.evolve': '{n} צאצאים מפותחים',
    'overview.event.ranking': 'איטרציה {iteration} · {n} עימותים',
    'overview.event.literature_review': '{n} מקורות',
    'overview.event.citation_audit':
      '{verified} מאומתים · {partial} חלקיים · {unsupported} ללא תמיכה · {unavailable} לא זמינים',
    'overview.event.report': 'הדוח נשמר',
    'overview.event.meta_review': 'ביקורת איטרציה {iteration}',
    'overview.event.supervisor.plan': 'תוכנית עם {n} סוכנים',
  },
};
