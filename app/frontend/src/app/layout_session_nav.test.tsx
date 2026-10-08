import {render} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import type {ChatSummary} from '@/shared/api/runs';
import {makeRun} from '@/shared/testing/fixtures';
import {installLayoutMocks} from './layout_test_support';
import {withExamples} from './layout_nav_rail';
import {
  preferredSessionSide,
  resultsPath,
  sessionEntryPath,
  useRecordRunTab,
  writeSessionSide,
} from '@/shared/hooks/session_side';

const ownChat: ChatSummary = {
  id: 'chat-1',
  title: 'My goal',
  challenge: 'My goal',
  status: 'active',
  run_id: null,
  created_at: 1,
  updated_at: 1,
};

describe('sidebar example entries', () => {
  it('lists unopened examples after the visitor’s own chats', () => {
    const demo = makeRun({id: 'demo-1', is_demo: true, title: 'Example: A'});
    const chats = withExamples([ownChat], [demo, makeRun({id: 'r2'})]);
    expect(chats.map(chat => chat.id)).toEqual(['chat-1', 'example:demo-1']);
    expect(chats[1].title).toBe('Example: A');
  });

  it('drops an example once the visitor has opened their copy', () => {
    const demo = makeRun({id: 'demo-1', is_demo: true});
    const copy = makeRun({
      id: 'copy-1',
      config: {...demo.config, example_source_id: 'demo-1'},
    });
    expect(withExamples([ownChat], [demo, copy])).toEqual([ownChat]);
  });
});

describe('layout session memory', () => {
  beforeEach(() => {
    installLayoutMocks();
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it('remembers the side per session', () => {
    writeSessionSide('run-1', 'chat');
    expect(preferredSessionSide('run-1')).toBe('chat');
  });
});

describe('run tab memory', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  function RecordAt({path}: {path: string}) {
    return (
      <MemoryRouter initialEntries={[path]}>
        <TabRecorder />
      </MemoryRouter>
    );
  }

  function TabRecorder() {
    useRecordRunTab();
    return null;
  }

  it('reopens Results on the tab last viewed for that run', () => {
    expect(resultsPath('run-1')).toBe('/runs/run-1/details');
    render(<RecordAt path="/runs/run-1/ideas" />);
    expect(resultsPath('run-1')).toBe('/runs/run-1/ideas');
    expect(resultsPath('run-2')).toBe('/runs/run-2/details');
  });

  it('sends every way back to the side and tab the reader left', () => {
    render(<RecordAt path="/runs/run-1/learning" />);
    writeSessionSide('run-1', 'results');
    expect(sessionEntryPath('run-1', 'chat-1')).toBe('/runs/run-1/learning');
    writeSessionSide('run-1', 'chat');
    expect(sessionEntryPath('run-1', 'chat-1')).toBe('/chats/chat-1');
    // A run without a chat can only reopen its Results.
    expect(sessionEntryPath('run-1', undefined)).toBe('/runs/run-1/learning');
  });
});
