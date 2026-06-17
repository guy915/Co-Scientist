// Evidence tab: citation-state labels, filters, empty states, source labels.
import type {Bundle} from '../types';

export const evidence: Bundle = {
  en: {
    // Citation states (STATE_STYLES labels)
    'evidence.state.verified': 'Verified',
    'evidence.state.partial': 'Partial',
    'evidence.state.unsupported': 'Unsupported',
    'evidence.state.unavailable': 'Unavailable',

    // Source row
    'evidence.etAl': ' et al.',
    'evidence.action.open': 'Open',

    // Empty state
    'evidence.empty.title': 'No evidence retrieved for this run.',
    'evidence.empty.note':
      "Literature review requires an MCP server (PubMed / INDRA). Without one the engine generates hypotheses from the model's training data only.",
  },
  he: {
    // Citation states (STATE_STYLES labels)
    'evidence.state.verified': 'מאומת',
    'evidence.state.partial': 'חלקי',
    'evidence.state.unsupported': 'ללא תימוכין',
    'evidence.state.unavailable': 'לא זמין',

    // Source row
    'evidence.etAl': ' ואחרים',
    'evidence.action.open': 'פתיחה',

    // Empty state
    'evidence.empty.title': 'לא אותרו ראיות עבור ריצה זו.',
    'evidence.empty.note':
      'סקירת ספרות מחייבת שרת MCP (PubMed / INDRA). ללא שרת כזה, המנוע מייצר השערות מנתוני האימון של המודל בלבד.',
  },
};
