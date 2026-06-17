// Chat tab: composer, mode toggles, message labels, and empty states.
import type {Bundle} from '../types';

export const chat: Bundle = {
  en: {
    'chat.empty.active':
      'Milestone updates will appear here. Send a message to steer the run or ask a question.',
    'chat.empty.inactive': 'No messages for this run.',
    'chat.thinking': 'Thinking…',
    'chat.answering': 'Answering…',
    'chat.placeholder.qa': 'Ask a question… (Ctrl+Enter to send)',
    'chat.placeholder.steering': 'Steer the run… (Ctrl+Enter to send)',
    'chat.mode.auto': 'auto',
    'chat.mode.steering': 'steering',
    'chat.mode.qa': 'qa',
    'chat.mode.autoEffective': 'auto · {mode}',
    'chat.steering.applied': 'Steering · applied',
    'chat.steering.pending': 'Steering · pending',
  },
  he: {
    'chat.empty.active':
      'עדכוני אבני דרך יופיעו כאן. שלחו הודעה כדי לכוון את הריצה או לשאול שאלה.',
    'chat.empty.inactive': 'אין הודעות עבור ריצה זו.',
    'chat.thinking': 'חושב…',
    'chat.answering': 'עונה…',
    'chat.placeholder.qa': 'שאלו שאלה… (Ctrl+Enter לשליחה)',
    'chat.placeholder.steering': 'כוונו את הריצה… (Ctrl+Enter לשליחה)',
    'chat.mode.auto': 'אוטומטי',
    'chat.mode.steering': 'כיוון',
    'chat.mode.qa': 'שאלות ותשובות',
    'chat.mode.autoEffective': 'אוטומטי · {mode}',
    'chat.steering.applied': 'כיוון · הוחל',
    'chat.steering.pending': 'כיוון · ממתין',
  },
};
