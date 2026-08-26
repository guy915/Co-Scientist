import {useState} from 'react';
import {type InterviewQuestion} from '@/api/runs';
import {Icon} from '@/components/icon';
import {joinClasses} from '../classes';
import {
  OPTION_CARD_BASE_CLASSES,
  OPTION_DESCRIPTION_CLASSES,
  OPTION_GRID_CLASSES,
  OPTION_INPUT_CLASSES,
  OPTION_LABEL_CLASSES,
  OPTION_MARKER_CLASSES,
  OPTION_MARKER_SELECTED_CLASSES,
  QUESTION_GROUP_CLASSES,
  QUESTION_OTHER_INPUT_CLASSES,
  QUESTION_PROMPT_CLASSES,
  QUESTIONS_HEAD_ACTIONS_CLASSES,
  QUESTIONS_HEAD_CLASSES,
  QUESTIONS_HEAD_LABEL_CLASSES,
  QUESTIONS_ICON_BUTTON_CLASSES,
  QUESTIONS_ICON_CLASSES,
  QUESTIONS_PANEL_CLASSES,
  QUESTION_CHECKBOX_MARKER_CLASSES,
  QUESTION_CHECKBOX_MARKER_SELECTED_CLASSES,
  QUESTION_CHECKBOX_TICK_CLASSES,
  QUESTIONS_SEND_ROW_CLASSES,
  SETUP_SECONDARY_BUTTON_CLASSES,
} from './chat_setup_classes';
import {
  answerText,
  emptySelections,
  isOtherOpen,
  type QuestionSelections,
  setOther,
  toggleOption,
  toggleOther,
} from './chat_questions';

/**
 * The answer that is not on offer.
 *
 * Every question carries it, whatever the model wrote: the options are the
 * answers the Agent could think of, and a scientist whose answer is none of
 * them must be able to say so without abandoning the chooser. Selecting it
 * opens a field rather than sending anything, so it never doubles as a
 * silent "skip".
 */
const OTHER_LABEL = 'Something else';

/** How a question's answers are read back to the scientist. */
const OTHER_PLACEHOLDER = 'Type your own answer';

export interface QuestionChooserProps {
  /** The questions the pending Agent turn offered, in the order asked. */
  questions: InterviewQuestion[];
  /** Posts the composed answer as the scientist's next turn. */
  onAnswer: (text: string) => void;
}

/**
 * The multiple-choice answers to the turn the Agent is waiting on.
 *
 * Rendered inside the composer's own form (see chat_composer.tsx), so it
 * reads as the input box expanding upward rather than as a card floating
 * over it -- and so the composer below stays fully usable. Answering by
 * clicking is an affordance, never a gate: the scientist can type a reply
 * instead, minimize this out of the way, or dismiss it outright, and the
 * turn is answered the same way in every case.
 *
 * Local state (what is chosen, whether it is minimized or dismissed) is
 * deliberately not lifted: it belongs to one pending turn and nothing
 * outside this component reads it. The caller remounts on a new turn by
 * keying on the turn id, which is what resets all three at once.
 */
export function QuestionChooser({questions, onAnswer}: QuestionChooserProps) {
  const [selections, setSelections] = useState(emptySelections);
  const [minimized, setMinimized] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const answer = answerText(questions, selections);
  const sendsOnClick = clickIsTheWholeAnswer(questions);
  const sendAnswer = () => onAnswer(answer);
  const choose = (index: number, label: string) => {
    const next = toggleOption(
      selections,
      index,
      label,
      questions[index].multi_select,
    );
    setSelections(next);
    if (sendsOnClick) onAnswer(answerText(questions, next));
  };

  return (
    <section className={QUESTIONS_PANEL_CLASSES} aria-label="Answer options">
      <ChooserHead
        label={headLabel(questions)}
        minimized={minimized}
        onToggleMinimize={() => setMinimized(open => !open)}
        onDismiss={() => setDismissed(true)}
      />
      {!minimized && (
        <ChooserBody
          questions={questions}
          selections={selections}
          setSelections={setSelections}
          onChoose={choose}
          send={needsSendControl(questions, selections) ? sendAnswer : null}
          answered={answer.length > 0}
        />
      )}
    </section>
  );
}

// Whether clicking an answer is the whole answer, so the chooser can send
// it there and then. One single-select question is: asking for a second
// click to confirm one radio button would be ceremony. Anything else --
// several questions, several answers, or an answer still being typed into
// the "something else" field -- is not finished until the scientist says
// it is, which is what the send control is for.
function clickIsTheWholeAnswer(questions: InterviewQuestion[]): boolean {
  return questions.length === 1 && !questions[0].multi_select;
}

// Whether the chooser needs a send control of its own. It does unless a
// click is the whole answer -- and it does again the moment the scientist
// opens a "something else" field, since what they are writing there has no
// other way to be committed. Showing it then, rather than once they have
// typed something, is what tells them how to finish.
function needsSendControl(
  questions: InterviewQuestion[],
  selections: QuestionSelections,
): boolean {
  if (!clickIsTheWholeAnswer(questions)) return true;
  return questions.some((_, index) => isOtherOpen(selections, index));
}

// What the chooser calls itself while it is collapsed: the headers of what
// it is asking about, or the questions themselves when they carry none.
function headLabel(questions: InterviewQuestion[]): string {
  return questions
    .map(question => question.header || question.question)
    .join(' · ');
}

// The chooser's title row. The minimize control's accessible name states
// what pressing it does, so the collapsed chooser is reachable by name
// rather than by remembering which chevron it was.
function ChooserHead({
  label,
  minimized,
  onToggleMinimize,
  onDismiss,
}: {
  label: string;
  minimized: boolean;
  onToggleMinimize: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className={QUESTIONS_HEAD_CLASSES}>
      <span className={QUESTIONS_HEAD_LABEL_CLASSES}>{label}</span>
      <div className={QUESTIONS_HEAD_ACTIONS_CLASSES}>
        <IconButton
          label={minimized ? 'Show the questions' : 'Minimize the questions'}
          icon={minimized ? 'expand_less' : 'expand_more'}
          onClick={onToggleMinimize}
        />
        <IconButton
          label="Dismiss the questions"
          icon="close"
          onClick={onDismiss}
        />
      </div>
    </div>
  );
}

// One of the chooser's two chrome controls. `type="button"` is load-bearing:
// the chooser renders inside the composer's form, where a bare button
// submits the message instead of minimizing anything.
function IconButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: 'expand_less' | 'expand_more' | 'close';
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={QUESTIONS_ICON_BUTTON_CLASSES}
      onClick={onClick}
    >
      <Icon aria-hidden="true" className={QUESTIONS_ICON_CLASSES} name={icon} />
    </button>
  );
}

// Props for ChooserBody, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface ChooserBodyProps {
  questions: InterviewQuestion[];
  selections: QuestionSelections;
  setSelections: (selections: QuestionSelections) => void;
  onChoose: (index: number, label: string) => void;
  /** Sends the composed answer, or null when a click already sends it. */
  send: (() => void) | null;
  answered: boolean;
}

// Every question, stacked, and the send control when one is needed.
function ChooserBody(props: ChooserBodyProps) {
  const {questions, selections, setSelections, onChoose, send} = props;
  return (
    <>
      {questions.map((question, index) => (
        <QuestionGroup
          key={question.question}
          question={question}
          index={index}
          selections={selections}
          setSelections={setSelections}
          onChoose={onChoose}
        />
      ))}
      {send && (
        <div className={QUESTIONS_SEND_ROW_CLASSES}>
          <button
            type="button"
            className={SETUP_SECONDARY_BUTTON_CLASSES}
            disabled={!props.answered}
            onClick={send}
          >
            Send answer
          </button>
        </div>
      )}
    </>
  );
}

// Props for QuestionGroup, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface QuestionGroupProps {
  question: InterviewQuestion;
  index: number;
  selections: QuestionSelections;
  setSelections: (selections: QuestionSelections) => void;
  onChoose: (index: number, label: string) => void;
}

// One question: its prompt, its answers as a card grid, and -- once the
// scientist has declined them all -- the field for their own wording.
function QuestionGroup(props: QuestionGroupProps) {
  const {question, index, selections, setSelections, onChoose} = props;
  const otherOpen = isOtherOpen(selections, index);
  return (
    <fieldset className={QUESTION_GROUP_CLASSES}>
      <legend className={QUESTION_PROMPT_CLASSES}>{question.question}</legend>
      <div className={OPTION_GRID_CLASSES}>
        {question.options.map(option => (
          <AnswerCard
            key={option.label}
            label={option.label}
            description={option.description}
            multiSelect={question.multi_select}
            selected={(selections.chosen[index] ?? []).includes(option.label)}
            onSelect={() => onChoose(index, option.label)}
          />
        ))}
        <AnswerCard
          label={OTHER_LABEL}
          description="Answer in your own words"
          multiSelect={question.multi_select}
          selected={otherOpen}
          onSelect={() => setSelections(toggleOther(selections, index))}
        />
      </div>
      {otherOpen && (
        <input
          autoFocus
          className={QUESTION_OTHER_INPUT_CLASSES}
          placeholder={OTHER_PLACEHOLDER}
          value={selections.other[index] ?? ''}
          onChange={event =>
            setSelections(setOther(selections, index, event.target.value))
          }
          // The composer's form surrounds this field, so an unhandled Enter
          // would send whatever is in the composer's textarea instead of
          // this answer. Swallowed rather than repurposed: the send control
          // is the one way to commit an answer that is still being written.
          onKeyDown={event => {
            if (event.key === 'Enter') event.preventDefault();
          }}
        />
      )}
    </fieldset>
  );
}

// The card's chosen/not-chosen mark: a radio disc when only one answer can
// hold, a ticked box when several can.
function AnswerMarker({
  multiSelect,
  selected,
}: {
  multiSelect: boolean;
  selected: boolean;
}) {
  if (!multiSelect) {
    return (
      <span
        aria-hidden="true"
        className={joinClasses(
          OPTION_MARKER_CLASSES,
          selected && OPTION_MARKER_SELECTED_CLASSES,
        )}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className={joinClasses(
        QUESTION_CHECKBOX_MARKER_CLASSES,
        selected && QUESTION_CHECKBOX_MARKER_SELECTED_CLASSES,
      )}
    >
      {selected && (
        <Icon name="check" className={QUESTION_CHECKBOX_TICK_CLASSES} />
      )}
    </span>
  );
}

// Props for AnswerCard, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface AnswerCardProps {
  label: string;
  description: string;
  multiSelect: boolean;
  selected: boolean;
  onSelect: () => void;
}

// One clickable answer, in the same radio-card language the run-spec card's
// Focus and Run type groups use. A real input carries the selection so the
// card is reachable and announced by a screen reader; `onClick` rather than
// `onChange` drives it, since re-clicking the chosen answer un-picks it and
// a radio input fires no change event for that.
function AnswerCard(props: AnswerCardProps) {
  const {label, description, multiSelect, selected, onSelect} = props;
  return (
    <label className={joinClasses(OPTION_CARD_BASE_CLASSES, 'cursor-pointer')}>
      <input
        type={multiSelect ? 'checkbox' : 'radio'}
        className={OPTION_INPUT_CLASSES}
        checked={selected}
        onChange={() => undefined}
        onClick={onSelect}
      />
      <AnswerMarker multiSelect={multiSelect} selected={selected} />
      <strong className={OPTION_LABEL_CLASSES}>{label}</strong>
      {description && (
        <small className={OPTION_DESCRIPTION_CLASSES}>{description}</small>
      )}
    </label>
  );
}
