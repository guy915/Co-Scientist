/**
 * Infers whether a chat message is a question (Q&A) or a steering
 * instruction, shared by the chat workspace and the run Chat tab.
 *
 * @param text The raw composer text.
 * @returns 'qa' when the text reads like a question, 'steering' otherwise.
 */
export function inferMessageMode(text: string): 'qa' | 'steering' {
  const trimmed = text.trim();
  if (
    trimmed.endsWith('?') ||
    /^(why|what|how|when|who|which|explain|tell me|can you|could you)\b/i.test(
      trimmed,
    )
  ) {
    return 'qa';
  }
  return 'steering';
}
