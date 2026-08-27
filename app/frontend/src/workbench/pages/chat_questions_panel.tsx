import {useState} from 'react';
import {type InterviewQuestion} from '@/api/runs';
import {Icon} from '@/components/icon';
import {joinClasses} from '../classes';
import {
  OPTION_INPUT_CLASSES,
  OPTION_LABEL_CLASSES,
  OPTION_MARKER_CLASSES,
  OPTION_MARKER_SELECTED_CLASSES,
  QUESTION_GROUP_CLASSES,
  QUESTION_OPTION_DESCRIPTION_CLASSES,
  QUESTION_OPTION_GRID_CLASSES,
  QUESTION_OPTION_ROW_CLASSES,
  QUESTION_OPTION_TEXT_CLASSES,
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
  type QuestionSelections,
  setOther,
  toggleOption,
} from './chat_questions';
import {QUESTION_OPTIONS_TOP_SPACING_CLASSES} from './chat_questions_classes';

/**
 * The answer that is not on offer.
 *
 * Every question carries it, whatever the model wrote: the options are the
 * answers the Agent could think of, and a scientist whose answer is none of
 * them must be able to say so without abandoning the chooser. It renders as
 * a typable field, not a card to click first -- writing in it is what
 * chooses it, and an empty field is a silent "skip" rather than a wrong one.
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
 *
 * Choosing an answer never sends it -- clicking, checking a box, and typing
 * into "Something else" all only update what is selected. The chooser's own
 * send control (always present, inert until something is chosen) is the one
 * way to commit the turn, so the scientist can change their mind, answer
 * several questions in any order, or add their own words before sending.
 */
export function QuestionChooser({questions, onAnswer}: QuestionChooserProps) {
  const [selections, setSelections] = useState(emptySelections);
  const [minimized, setMinimized] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const answer = answerText(questions, selections);
  const sendAnswer = () => onAnswer(answer);
  const choose = (index: number, label: string) => {
    setSelections(
      toggleOption(selections, index, label, questions[index].multi_select),
    );
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
          send={sendAnswer}
          answered={answer.length > 0}
        />
      )}
    </section>
  );
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
  /** Sends the composed answer. */
  send: () => void;
  answered: boolean;
}

// Every question, stacked, then the chooser's own send control -- always
// present, so it reads as the way to commit an answer whether the scientist
// picked one option or is still filling in several questions.
function ChooserBody(props: ChooserBodyProps) {
  const {questions, selections, setSelections, onChoose, send, answered} =
    props;
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
      <div className={QUESTIONS_SEND_ROW_CLASSES}>
        <button
          type="button"
          className={SETUP_SECONDARY_BUTTON_CLASSES}
          disabled={!answered}
          onClick={send}
        >
          Send answer
        </button>
      </div>
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

// One question: its prompt, then its answers as a single-column list of
// full-width rows, the scientist's own-words field always the last of them.
function QuestionGroup(props: QuestionGroupProps) {
  const {question, index, selections, setSelections, onChoose} = props;
  return (
    <fieldset className={QUESTION_GROUP_CLASSES}>
      <legend className={QUESTION_PROMPT_CLASSES}>{question.question}</legend>
      <div
        className={joinClasses(
          QUESTION_OPTION_GRID_CLASSES,
          QUESTION_OPTIONS_TOP_SPACING_CLASSES,
        )}
      >
        {question.options.map(option => (
          <AnswerRow
            key={option.label}
            label={option.label}
            description={option.description}
            multiSelect={question.multi_select}
            selected={(selections.chosen[index] ?? []).includes(option.label)}
            onSelect={() => onChoose(index, option.label)}
          />
        ))}
        <OtherAnswerRow
          multiSelect={question.multi_select}
          text={selections.other[index] ?? ''}
          onChangeText={text =>
            setSelections(setOther(selections, index, text))
          }
        />
      </div>
    </fieldset>
  );
}

// The row standing in for "Something else": typing into it is what chooses
// it, so unlike AnswerRow there is no click handler and no separate hidden
// input -- the visible field itself carries the selection.
function OtherAnswerRow({
  multiSelect,
  text,
  onChangeText,
}: {
  multiSelect: boolean;
  text: string;
  onChangeText: (text: string) => void;
}) {
  return (
    <div className={QUESTION_OPTION_ROW_CLASSES}>
      <AnswerMarker
        multiSelect={multiSelect}
        selected={text.trim().length > 0}
      />
      <input
        className={QUESTION_OTHER_INPUT_CLASSES}
        aria-label={OTHER_LABEL}
        placeholder={OTHER_PLACEHOLDER}
        value={text}
        onChange={event => onChangeText(event.target.value)}
        // The composer's form surrounds this field, so an unhandled Enter
        // would send whatever is in the composer's textarea instead of
        // this answer. Swallowed rather than repurposed: the send control
        // is the one way to commit an answer, and typing must never submit
        // anything on its own.
        onKeyDown={event => {
          if (event.key === 'Enter') event.preventDefault();
        }}
      />
    </div>
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

// Props for AnswerRow, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface AnswerRowProps {
  label: string;
  description: string;
  multiSelect: boolean;
  selected: boolean;
  onSelect: () => void;
}

// One clickable answer, a full-width row with its label and description
// running side by side. A real input carries the selection so the row is
// reachable and announced by a screen reader; `onClick` rather than
// `onChange` drives it, since re-clicking the chosen answer un-picks it and
// a radio input fires no change event for that.
function AnswerRow(props: AnswerRowProps) {
  const {label, description, multiSelect, selected, onSelect} = props;
  return (
    <label
      className={joinClasses(QUESTION_OPTION_ROW_CLASSES, 'cursor-pointer')}
    >
      <input
        type={multiSelect ? 'checkbox' : 'radio'}
        className={OPTION_INPUT_CLASSES}
        checked={selected}
        onChange={() => undefined}
        onClick={onSelect}
      />
      <AnswerMarker multiSelect={multiSelect} selected={selected} />
      <span className={QUESTION_OPTION_TEXT_CLASSES}>
        <strong className={OPTION_LABEL_CLASSES}>{label}</strong>
        {description && (
          <small className={QUESTION_OPTION_DESCRIPTION_CLASSES}>
            {description}
          </small>
        )}
      </span>
    </label>
  );
}
