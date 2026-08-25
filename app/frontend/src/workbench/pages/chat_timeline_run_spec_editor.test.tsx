import {fireEvent, render, screen} from '@testing-library/react';
import {beforeEach, expect, test, vi} from 'vitest';
import type {Interview} from '@/api/runs';
import {editInterviewFields} from '@/api/runs';
import {makeSpec} from '@/test_fixtures';
import {SpecFieldsSection} from './chat_timeline_run_spec_editor';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {...actual, editInterviewFields: vi.fn()};
});

beforeEach(() => {
  vi.clearAllMocks();
});

function renderSection(overrides: Parameters<typeof makeSpec>[0] = {}) {
  const onFieldsChange = vi.fn();
  const spec = makeSpec({interviewId: 'interview-1', ...overrides});
  render(
    <SpecFieldsSection
      spec={spec}
      locked={false}
      onFieldsChange={onFieldsChange}
    />,
  );
  return {spec, onFieldsChange};
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

test('offers no in-place editing when locked or without an interview id', () => {
  const withInterview = render(
    <SpecFieldsSection
      spec={makeSpec({interviewId: 'interview-1'})}
      locked={false}
      onFieldsChange={vi.fn()}
    />,
  );
  expect(screen.getByText('Edit details')).toBeInTheDocument();
  withInterview.unmount();

  const noInterviewId = render(
    <SpecFieldsSection
      spec={makeSpec({interviewId: undefined})}
      locked={false}
      onFieldsChange={vi.fn()}
    />,
  );
  expect(screen.queryByText('Edit details')).not.toBeInTheDocument();
  noInterviewId.unmount();

  render(
    <SpecFieldsSection
      spec={makeSpec({interviewId: 'interview-1'})}
      locked
      onFieldsChange={vi.fn()}
    />,
  );
  expect(screen.queryByText('Edit details')).not.toBeInTheDocument();
});

test('entering edit mode shows the current field values', () => {
  renderSection({
    goal: 'Study liver fibrosis',
    attributes: ['Attr A'],
    requirements: ['Req A'],
    title: 'A title',
  });

  fireEvent.click(screen.getByText('Edit details'));

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

  fireEvent.click(screen.getByText('Edit details'));
  fireEvent.change(screen.getByLabelText('Research Challenge'), {
    target: {value: 'Study liver fibrosis, revised'},
  });
  fireEvent.click(screen.getByText('Save'));

  await screen.findByText('Edit details');
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

  fireEvent.click(screen.getByText('Edit details'));
  fireEvent.click(screen.getByText('Add focus area'));
  fireEvent.change(screen.getByLabelText('Focus Area item 2'), {
    target: {value: 'Attr B'},
  });
  fireEvent.click(screen.getByLabelText('Remove "Attr A" from Focus Area'));
  fireEvent.click(screen.getByLabelText('Remove "Req A" from Preferences'));
  fireEvent.click(screen.getByText('Save'));

  await screen.findByText('Edit details');
  expect(editInterviewFields).toHaveBeenCalledWith(
    'interview-1',
    expect.objectContaining({focus_area: ['Attr B'], preferences: []}),
  );
});

test('Cancel restores the original values without saving', () => {
  const {onFieldsChange} = renderSection({goal: 'Original goal'});

  fireEvent.click(screen.getByText('Edit details'));
  fireEvent.change(screen.getByLabelText('Research Challenge'), {
    target: {value: 'Changed but abandoned'},
  });
  fireEvent.click(screen.getByText('Cancel'));

  expect(editInterviewFields).not.toHaveBeenCalled();
  expect(onFieldsChange).not.toHaveBeenCalled();
  expect(screen.getByText('Original goal')).toBeInTheDocument();

  fireEvent.click(screen.getByText('Edit details'));
  expect(screen.getByLabelText('Research Challenge')).toHaveValue(
    'Original goal',
  );
});

test('disables Save while the goal is empty', () => {
  renderSection({goal: 'Not empty'});

  fireEvent.click(screen.getByText('Edit details'));
  fireEvent.change(screen.getByLabelText('Research Challenge'), {
    target: {value: '   '},
  });

  expect(screen.getByText('Save')).toBeDisabled();
});
