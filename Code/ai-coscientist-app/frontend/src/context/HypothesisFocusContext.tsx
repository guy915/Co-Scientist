import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useState } from "react";

interface HypothesisFocusContextValue {
  pinnedText: string | null;
  trackedTexts: Set<string>;
  // extras: additional text variants (e.g. hyp.hypothesis alias) seeded at pin time
  pin: (text: string, extras?: string[]) => void;
  unpin: () => void;
  trackEvolution: (originalText: string, evolvedText: string) => void;
  // true if the given text (after trim) matches any tracked entry
  isTracked: (text: string) => boolean;
}

const HypothesisFocusContext = createContext<HypothesisFocusContextValue>({
  pinnedText: null,
  trackedTexts: new Set(),
  pin: () => {},
  unpin: () => {},
  trackEvolution: () => {},
  isTracked: () => false,
});

export function HypothesisFocusProvider({ children }: { children: ReactNode }) {
  const [pinnedText, setPinnedText] = useState<string | null>(null);
  const [trackedTexts, setTrackedTexts] = useState<Set<string>>(new Set());

  const pin = useCallback((text: string, extras: string[] = []) => {
    const trimmed = text.trim();
    const seed = new Set([trimmed, ...extras.map((t) => t.trim())].filter(Boolean));
    setPinnedText(trimmed);
    setTrackedTexts(seed);
  }, []);

  const unpin = useCallback(() => {
    setPinnedText(null);
    setTrackedTexts(new Set());
  }, []);

  const trackEvolution = useCallback((originalText: string, evolvedText: string) => {
    const orig = originalText.trim();
    const evol = evolvedText.trim();
    setTrackedTexts((prev) => {
      if (prev.has(orig) && !prev.has(evol)) {
        return new Set([...prev, evol]);
      }
      return prev;
    });
  }, []);

  const isTracked = useCallback(
    (text: string) => {
      return trackedTexts.has(text.trim());
    },
    [trackedTexts]
  );

  return (
    <HypothesisFocusContext.Provider
      value={{ pinnedText, trackedTexts, pin, unpin, trackEvolution, isTracked }}
    >
      {children}
    </HypothesisFocusContext.Provider>
  );
}

export function useHypothesisFocus() {
  return useContext(HypothesisFocusContext);
}
