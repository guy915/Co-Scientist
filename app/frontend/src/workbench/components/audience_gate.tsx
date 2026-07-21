import {useEffect, useRef} from 'react';
import {useAudience} from '../audience_context';

/**
 * First-visit gate. Renders nothing itself: while no audience has been chosen
 * it holds the Settings dialog open on its Affiliation section, so the chooser
 * is the same surface used to change the answer later.
 *
 * The question is asked on every route, and the chooser cannot be dismissed
 * unanswered — Layout marks it non-dismissible while the audience is unset
 * (see SettingsDialog's `dismissible` prop), and this effect re-opens it if it
 * closes anyway. Deep-linking to an inner route is therefore not a way around
 * the question.
 *
 * Answering dismisses it: the gate closes the chooser it opened, so picking
 * an option returns the user to the page they asked for rather than leaving
 * Settings sitting over it.
 *
 * @param props.onOpenAffiliation Opens Settings on the Affiliation section.
 * @param props.onCloseChooser Closes the Settings dialog again.
 * @param props.chooserOpen Whether the Affiliation chooser is currently
 *   showing.
 */
export function AudienceGate({
  onOpenAffiliation,
  onCloseChooser,
  chooserOpen,
}: {
  onOpenAffiliation: () => void;
  onCloseChooser: () => void;
  chooserOpen: boolean;
}) {
  const {audience} = useAudience();
  // Only a chooser this gate forced open is auto-closed on an answer; a
  // Settings dialog the user opened themselves is theirs to close.
  const openedByGate = useRef(false);

  useEffect(() => {
    if (audience || chooserOpen) return;
    openedByGate.current = true;
    onOpenAffiliation();
  }, [audience, chooserOpen, onOpenAffiliation]);

  useEffect(() => {
    if (!audience || !openedByGate.current) return;
    openedByGate.current = false;
    onCloseChooser();
  }, [audience, onCloseChooser]);

  return null;
}
