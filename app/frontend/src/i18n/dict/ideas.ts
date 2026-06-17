// Hypotheses list (IdeasTab) and detail dialog (IdeaModal).
import type {Bundle} from '../types';

export const ideas: Bundle = {
  en: {
    // Empty state
    'ideas.empty': 'Hypotheses appear here once the generation node runs.',

    // Filter / sort options
    'ideas.filter.initial': 'Initial',
    'ideas.filter.evolved': 'Evolved',
    'ideas.sort.title': 'Title',
    'ideas.sort.generation': 'Generation',

    // Row badges and meta
    'ideas.badge.elo': 'Elo {rating}',
    'ideas.badge.gen': 'Gen {generation}',
    'ideas.badge.winLoss': '{wins}W / {losses}L',
    'ideas.badge.verified': '{verified}/{total} Verified',
    'ideas.field.mechanism': 'Mechanism:',
    'ideas.field.expectedEffect': 'Expected effect:',
    'ideas.reviews.count': '{count} review',
    'ideas.reviews.count_plural': '{count} reviews',
    'ideas.action.openDetail': 'Open detail',

    // Modal header
    'ideas.modal.meta': 'gen {generation} · {agent}',
    'ideas.modal.winLoss': '{wins}W · {losses}L',

    // Modal sections
    'ideas.section.statement': 'Statement',
    'ideas.section.mechanism': 'Mechanism',
    'ideas.section.expectedEffect': 'Expected effect',
    'ideas.section.experimentalDesign': 'Experimental design',
    'ideas.section.lineage': 'Lineage',
    'ideas.section.reviews': 'Reviews & critique',
    'ideas.section.citations': 'Citations',

    // Lineage entries
    'ideas.lineage.parent': '↑ Parent: {title}',
    'ideas.lineage.child': '↓ Child: {title}',
  },
  he: {
    // Empty state
    'ideas.empty': 'ההשערות יופיעו כאן לאחר שצומת היצירה ירוץ.',

    // Filter / sort options
    'ideas.filter.initial': 'ראשוניות',
    'ideas.filter.evolved': 'מפותחות',
    'ideas.sort.title': 'כותרת',
    'ideas.sort.generation': 'דור',

    // Row badges and meta
    'ideas.badge.elo': 'Elo {rating}',
    'ideas.badge.gen': 'דור {generation}',
    'ideas.badge.winLoss': '{wins}נ׳ / {losses}ה׳',
    'ideas.badge.verified': '{verified}/{total} מאומתות',
    'ideas.field.mechanism': 'מנגנון:',
    'ideas.field.expectedEffect': 'השפעה צפויה:',
    'ideas.reviews.count': 'ביקורת {count}',
    'ideas.reviews.count_plural': '{count} ביקורות',
    'ideas.action.openDetail': 'פתיחת פירוט',

    // Modal header
    'ideas.modal.meta': 'דור {generation} · {agent}',
    'ideas.modal.winLoss': '{wins}נ׳ · {losses}ה׳',

    // Modal sections
    'ideas.section.statement': 'טענה',
    'ideas.section.mechanism': 'מנגנון',
    'ideas.section.expectedEffect': 'השפעה צפויה',
    'ideas.section.experimentalDesign': 'תכנון ניסויי',
    'ideas.section.lineage': 'שושלת',
    'ideas.section.reviews': 'ביקורות וביקורת',
    'ideas.section.citations': 'ציטוטים',

    // Lineage entries
    'ideas.lineage.parent': '↑ הורה: {title}',
    'ideas.lineage.child': '↓ צאצא: {title}',
  },
};
