import {makeQuestion} from '@/test_fixtures';
import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import type {Interview, InterviewQuestion} from '@/api/runs';
import {
  apiMock,
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';

const MODEL_SYSTEM: InterviewQuestion = makeQuestion();

function asking(questions: InterviewQuestion[]): Interview {
  return {
    id: 'interview-1',
    client_id: 'scientist-a',
    status: 'active',
    fields: {
      research_challenge: 'Reverse cardiac fibrosis',
      focus_area: [],
      preferences: [],
      title: null,
    },
    current_question: MODEL_SYSTEM.question,
    documents: [],
    turns: [
      {
        id: 1,
        role: 'user',
        content: 'Reverse cardiac fibrosis',
        reasoning: null,
        fallback: false,
        questions: [],
        created_at: 1,
      },
      {
        id: 2,
        role: 'agent',
        content: 'A few directions are worth separating here.',
        reasoning: null,
        fallback: false,
        questions,
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: null,
  };
}

// The chooser adds another textbox; identify the composer by its element type.
function getComposer(): HTMLElement {
  return screen.getAllByRole('textbox').find(el => el.tagName === 'TEXTAREA')!;
}

async function askTheScientist(questions = [MODEL_SYSTEM]) {
  apiMock.createInterview.mockResolvedValue(asking(questions));
  apiMock.addInterviewTurn.mockResolvedValue(asking([]));
  renderWorkspace();
  fireEvent.change(screen.getByRole('textbox'), {
    target: {value: 'Reverse cardiac fibrosis'},
  });
  fireEvent.click(screen.getByRole('button', {name: 'Send'}));
  return screen.findByText(MODEL_SYSTEM.question);
}

beforeEach(() => {
  installChatWorkspaceMocks();
  vi.clearAllMocks();
});

it('offers the turn answers inside the composer, above the input', async () => {
  const prompt = await askTheScientist();
  expect(prompt.closest('form')).toBe(getComposer().closest('form'));
});

it('sends a clicked answer as the scientist own next turn', async () => {
  await askTheScientist();
  fireEvent.click(screen.getByLabelText(/iPSC-derived line/));
  fireEvent.click(screen.getByRole('button', {name: /send answer/i}));
  await waitFor(() => {
    expect(apiMock.addInterviewTurn).toHaveBeenCalledWith(
      'interview-1',
      'Model system: iPSC-derived line',
      expect.anything(),
      [],
      expect.anything(),
    );
  });
});

it('leaves the composer usable, and typing past the questions still works', async () => {
  await askTheScientist();
  const textbox = getComposer();
  expect(textbox).toBeEnabled();
  fireEvent.change(textbox, {target: {value: 'None of those — human atria'}});
  fireEvent.click(screen.getByRole('button', {name: 'Send'}));
  await waitFor(() => {
    expect(apiMock.addInterviewTurn).toHaveBeenCalledWith(
      'interview-1',
      'None of those — human atria',
      expect.anything(),
      [],
      expect.anything(),
    );
  });
});

it('keeps a half-written message when an answer is clicked instead', async () => {
  await askTheScientist();
  const textbox = getComposer();
  fireEvent.change(textbox, {target: {value: 'also, note that'}});
  fireEvent.click(screen.getByLabelText(/Primary human cells/));
  fireEvent.click(screen.getByRole('button', {name: /send answer/i}));
  await waitFor(() => {
    expect(apiMock.addInterviewTurn).toHaveBeenCalled();
  });
  expect(textbox).toHaveValue('also, note that');
});

it('stops offering the answers once the turn they belonged to is answered', async () => {
  await askTheScientist();
  fireEvent.click(screen.getByLabelText(/Primary human cells/));
  fireEvent.click(screen.getByRole('button', {name: /send answer/i}));
  await waitFor(() => {
    expect(screen.queryByText(MODEL_SYSTEM.question)).toBeNull();
  });
});
