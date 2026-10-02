import {Icon} from '@/components/icon';
import {joinClasses} from '../classes';
import {type Suggestion} from './chat_home_suggestions';
import {TruncatedLabel} from '../components/truncated_label';

// Renders the suggestion prompt row: one SuggestionCard per entry in
// SUGGESTIONS, wired to the shared hover/preview state and the handler that
// fills the composer when a card is selected.
export function HomeSuggestionRow({
  isMobile,
  suggestions,
  hoveredSuggestion,
  onPreview,
  onSelect,
}: {
  isMobile: boolean;
  suggestions: readonly Suggestion[];
  hoveredSuggestion: string | null;
  onPreview: (text: string | null) => void;
  onSelect: (text: string) => void;
}) {
  return (
    <div className="reference-suggestion-row">
      {suggestions.map((suggestion, index) => (
        <SuggestionCard
          key={suggestion.preview}
          suggestion={suggestion}
          index={index}
          isMobile={isMobile}
          isPreviewed={hoveredSuggestion === suggestion.preview}
          onPreview={onPreview}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

// The preview bubble's anchor class for a suggestion card's column position
// (first/middle/last), so it stays roughly centered over the row rather than
// overflowing past the viewport edge for the first/last card.
function suggestionPreviewPositionClass(index: number) {
  if (index === 0) return 'reference-suggestion-preview--start';
  if (index === 1) return 'reference-suggestion-preview--center';
  return 'reference-suggestion-preview--end';
}

// Renders one suggestion card in the home-stage suggestion row: the
// hover/focus-revealed one-sentence preview bubble (SuggestionPreviewBubble),
// and the button that fills the composer with the suggestion's full prompt
// when selected (SuggestionTriggerButton).
function SuggestionCard({
  suggestion,
  index,
  isMobile,
  isPreviewed,
  onPreview,
  onSelect,
}: {
  suggestion: Suggestion;
  index: number;
  isMobile: boolean;
  isPreviewed: boolean;
  onPreview: (preview: string | null) => void;
  onSelect: (prompt: string) => void;
}) {
  // The preview bubble anchors differently per column (start/center/end) so
  // it stays roughly centered over the row rather than overflowing past the
  // viewport edge for the first/last card.
  const previewPositionClass = suggestionPreviewPositionClass(index);

  return (
    <div className="reference-suggestion-slot">
      <SuggestionPreviewBubble
        text={suggestion.preview}
        isPreviewed={isPreviewed}
        positionClass={previewPositionClass}
      />
      <SuggestionTriggerButton
        suggestion={suggestion}
        isMobile={isMobile}
        isPreviewed={isPreviewed}
        onPreview={onPreview}
        onSelect={onSelect}
      />
    </div>
  );
}

// One-sentence preview bubble revealed above a suggestion card on hover/focus.
function SuggestionPreviewBubble({
  text,
  isPreviewed,
  positionClass,
}: {
  text: string;
  isPreviewed: boolean;
  positionClass: string;
}) {
  return (
    <p
      className={joinClasses(
        'reference-suggestion-preview',
        positionClass,
        isPreviewed && 'visible',
      )}
      aria-hidden={!isPreviewed}
    >
      {text}
    </p>
  );
}

// Props for SuggestionTriggerButton, named at module level per the
// destructured prop signature otherwise pushing the component past the line
// cap.
interface SuggestionTriggerButtonProps {
  suggestion: Suggestion;
  isMobile: boolean;
  isPreviewed: boolean;
  onPreview: (preview: string | null) => void;
  onSelect: (prompt: string) => void;
}

// The suggestion's clickable trigger: fills the composer with the
// suggestion's full prompt when clicked, and drives the preview bubble's
// visibility on hover/pointer/focus so touch/keyboard users get the same
// one-sentence preview that mouse hover provides.
function SuggestionTriggerButton(props: SuggestionTriggerButtonProps) {
  const {suggestion, isMobile, isPreviewed, onPreview, onSelect} = props;
  return (
    <button
      type="button"
      className={joinClasses(
        'reference-suggestion-button',
        isPreviewed && 'is-previewed',
      )}
      onPointerEnter={() => onPreview(suggestion.preview)}
      onPointerLeave={() => onPreview(null)}
      onFocus={() => onPreview(suggestion.preview)}
      onBlur={() => onPreview(null)}
      onClick={() => onSelect(suggestion.prompt)}
    >
      {/* Leading glyph is part of the phone list layout only; desktop cards
          are text-only. */}
      {isMobile && (
        <Icon
          aria-hidden="true"
          className="reference-suggestion-icon"
          name={suggestion.icon}
        />
      )}
      <TruncatedLabel
        className="reference-suggestion-text"
        text={suggestion.preview}
        lines={isMobile ? 1 : 2}
      />
    </button>
  );
}
