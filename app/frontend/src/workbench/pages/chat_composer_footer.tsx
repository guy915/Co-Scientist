import {type ChangeEvent, type RefObject} from 'react';
import {Icon} from '@/components/icon';
import {tooltipClassNames} from '../tooltip';
import {
  COMPOSER_ACTIONS_CLASSES,
  COMPOSER_SOURCE_ICON_CLASSES,
  COMPOSER_SUBMIT_BUTTON_CLASSES,
} from './chat_home_classes';
import {
  type ConnectorToggleProps,
  SourceControls,
} from './chat_composer_connectors';

// The composer's footer controls row: the file/connector source controls
// plus the submit (or Stop, mid-turn) button. Split out of chat_composer.tsx
// to keep that file under the repo's line cap.

// Stop, shown in place of Send while a turn the scientist can interrupt is
// in flight. A plain `type="button"` so a click never submits the form --
// the composer's own submit path stays the only way to send a message.
function ComposerStopButton({onStop}: {onStop?: () => void}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: COMPOSER_SUBMIT_BUTTON_CLASSES,
        placement: 'top',
      })}
      aria-label="Stop"
      data-tooltip="Stop"
      onClick={onStop}
    >
      <Icon
        aria-hidden="true"
        className={COMPOSER_SOURCE_ICON_CLASSES}
        name="stop"
      />
    </button>
  );
}

function ComposerSendButton({disabled}: {disabled: boolean}) {
  return (
    <button
      type="submit"
      className={tooltipClassNames({
        className: COMPOSER_SUBMIT_BUTTON_CLASSES,
        placement: 'top',
      })}
      aria-label="Send"
      data-tooltip="Submit"
      disabled={disabled}
    >
      <Icon
        aria-hidden="true"
        className={COMPOSER_SOURCE_ICON_CLASSES}
        name="send"
      />
    </button>
  );
}

// Props for ComposerFooter, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
export interface ComposerFooterProps {
  connectorsOpen: boolean;
  onToggleConnectors: () => void;
  sourceControlsRef: RefObject<HTMLDivElement | null>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFilesChanged: (e: ChangeEvent<HTMLInputElement>) => void;
  connectors: ConnectorToggleProps;
  submitDisabled: boolean;
  disabled: boolean;
  stoppable: boolean;
  onStop?: () => void;
}

export function ComposerFooter(props: ComposerFooterProps) {
  const {
    connectorsOpen,
    onToggleConnectors,
    sourceControlsRef,
    fileInputRef,
    onFilesChanged,
    connectors,
    submitDisabled,
    disabled,
    stoppable,
    onStop,
  } = props;
  return (
    <div className={COMPOSER_ACTIONS_CLASSES}>
      <SourceControls
        connectorsOpen={connectorsOpen}
        onToggleConnectors={onToggleConnectors}
        sourceControlsRef={sourceControlsRef}
        fileInputRef={fileInputRef}
        onFilesChanged={onFilesChanged}
        connectors={connectors}
        disabled={disabled}
      />
      {stoppable ? (
        <ComposerStopButton onStop={onStop} />
      ) : (
        <ComposerSendButton disabled={submitDisabled} />
      )}
    </div>
  );
}
