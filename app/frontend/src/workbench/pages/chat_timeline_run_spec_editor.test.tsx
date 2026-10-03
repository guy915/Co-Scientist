import {fireEvent, render, screen} from '@testing-library/react';
import {beforeEach, expect, test, vi} from 'vitest';
import type {Interview} from '@/api/runs';
import {editInterviewFields} from '@/api/runs';
import {makeSpec} from '@/test_fixtures';
import type {InferredRunSpec} from '../run_spec';
import {
  SpecFieldsSection,
  useSpecFieldsEditor,
} from './chat_timeline_run_spec_editor';
import {RunSpecCard} from './chat_timeline_run_spec_card';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {...actual, editInterviewFields: vi.fn()};
});

beforeEach(() => {
  vi.clearAllMocks();
});

function Harness({
  spec,
  onFieldsChange,
}: {
  spec: InferredRunSpec;
  onFieldsChange: (patch: Partial<InferredRunSpec>) => void;
}) {
  const editor = useSpecFieldsEditor(spec, onFieldsChange);
  return (
    <>
      {!editor.editing && (
        <button type="button" onClick={editor.startEditing}>
          Edit plan
        </button>
      )}
      <SpecFieldsSection spec={spec} editor={editor} />
    </>
  );
}

function renderSection(overrides: Parameters<typeof makeSpec>[0] = {}) {
  const onFieldsChange = vi.fn();
  const spec = makeSpec({interviewId: 'interview-1', ...overrides});
  render(<Harness spec={spec} onFieldsChange={onFieldsChange} />);
  return {spec, onFieldsChange};
}

function cardProps(spec: InferredRunSpec, locked = false) {
  return {
    spec,
    isStarting: false,
    locked,
    onFocusChange: vi.fn(),
    onTierChange: vi.fn(),
    onNotificationChange: vi.fn(),
    onFieldsChange: vi.fn(),
    onCancel: vi.fn(),
    onRetry: vi.fn(),
    onStart: vi.fn(),
  };
}

function renderCard(spec: InferredRunSpec, locked = false) {
  render(<RunSpecCard {...cardProps(spec, locked)} />);
}

function updatedInterview(over: Partial<Interview['fields']> = {}): Interview {
  return {
    id: 'interview-1',
    client_id: 'c1',
    status: 'active',
    fields: {
      research_challenge: 'Study liver fibrosis, revised',
      focus_area: ['Attr A'],
      preferences: ['Req A'],
      title: null,
      ...over,
    },
    current_question: null,
    turns: [],
    documents: [],
    created_at: 0,
    updated_at: 0,
    completed_at: null,
  };
}

test('the plan card offers its pencil, and hides it once the form is open', () => {
  renderCard(makeSpec({interviewId: 'interview-1'}));

  fireEvent.click(screen.getByLabelText('Edit plan'));

  expect(screen.queryByLabelText('Edit plan')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Research Challenge')).toBeInTheDocument();
});

test('the plan card hides its pencil when there is nothing to edit', () => {
  const withoutInterview = render(
    <RunSpecCard {...cardProps(makeSpec({interviewId: undefined}))} />,
  );
  expect(screen.queryByLabelText('Edit plan')).not.toBeInTheDocument();
  withoutInterview.unmount();

  renderCard(makeSpec({interviewId: 'interview-1'}), true);
  expect(screen.queryByLabelText('Edit plan')).not.toBeInTheDocument();
});

test('entering edit mode shows the current field values', () => {
  renderSection({
    goal: 'Study liver fibrosis',
    attributes: ['Attr A'],
    requirements: ['Req A'],
    title: 'A title',
  });

  fireEvent.click(screen.getByText('Edit plan'));

  expect(screen.getByLabelText('Research Challenge')).toHaveValue(
    'Study liver fibrosis',
  );
  expect(screen.getByLabelText('Title')).toHaveValue('A title');
  expect(screen.getByLabelText('Focus Area item 1')).toHaveValue('Attr A');
  expect(screen.getByLabelText('Preferences item 1')).toHaveValue('Req A');
});

test('saving calls editInterviewFields with the mapped payload and applies the result', async () => {
  vi.mocked(editInterviewFields).mockResolvedValue(updatedInterview());
  const {onFieldsChange} = renderSection({
    goal: 'Study liver fibrosis',
    attributes: ['Attr A'],
    requirements: ['Req A'],
    title: null,
  });

  fireEvent.click(screen.getByText('Edit plan'));
  fireEvent.change(screen.getByLabelText('Research Challenge'), {
    target: {value: 'Study liver fibrosis, revised'},
  });
  fireEvent.click(screen.getByText('Save'));

  await screen.findByText('Edit plan');
  expect(editInterviewFields).toHaveBeenCalledWith('interview-1', {
    research_challenge: 'Study liver fibrosis, revised',
    focus_area: ['Attr A'],
    preferences: ['Req A'],
    title: null,
  });
  expect(onFieldsChange).toHaveBeenCalledWith({
    interviewId: 'interview-1',
    title: null,
    goal: 'Study liver fibrosis, revised',
    attributes: ['Attr A'],
    requirements: ['Req A'],
  });
});

test('adds and removes list entries', async () => {
  vi.mocked(editInterviewFields).mockResolvedValue(updatedInterview());
  renderSection({attributes: ['Attr A'], requirements: ['Req A']});

  fireEvent.click(screen.getByText('Edit plan'));
  fireEvent.click(screen.getByText('Add focus area'));
  fireEvent.change(screen.getByLabelText('Focus Area item 2'), {
    target: {value: 'Attr B'},
  });
  fireEvent.click(screen.getByLabelText('Remove "Attr A" from Focus Area'));
  fireEvent.click(screen.getByLabelText('Remove "Req A" from Preferences'));
  fireEvent.click(screen.getByText('Save'));

  await screen.findByText('Edit plan');
  expect(editInterviewFields).toHaveBeenCalledWith(
    'interview-1',
    expect.objectContaining({focus_area: ['Attr B'], preferences: []}),
  );
});

test('Cancel restores the original values without saving', () => {
  const {onFieldsChange} = renderSection({goal: 'Original goal'});

  fireEvent.click(screen.getByText('Edit plan'));
  fireEvent.change(screen.getByLabelText('Research Challenge'), {
    target: {value: 'Changed but abandoned'},
  });
  fireEvent.click(screen.getByText('Cancel'));

  expect(editInterviewFields).not.toHaveBeenCalled();
  expect(onFieldsChange).not.toHaveBeenCalled();
  expect(screen.getByText('Original goal')).toBeInTheDocument();

  fireEvent.click(screen.getByText('Edit plan'));
  expect(screen.getByLabelText('Research Challenge')).toHaveValue(
    'Original goal',
  );
});

test('disables Save while the goal is empty', () => {
  renderSection({goal: 'Not empty'});

  fireEvent.click(screen.getByText('Edit plan'));
  fireEvent.change(screen.getByLabelText('Research Challenge'), {
    target: {value: '   '},
  });

  expect(screen.getByText('Save')).toBeDisabled();
});
