/** User-facing next step for terminal failures with an exact known cause. */
export function runFailureGuidance(
  failureKind: string | null | undefined,
): {message: string; toast: string} | null {
  switch (failureKind) {
    case 'llm_call_budget_exceeded':
      return {
        message:
          'The run reached its configured model-call limit before it completed. Start a new run with a narrower research goal.',
        toast: 'Run failed. See the suggested next step below.',
      };
    case 'llm_timeout':
      return {
        message:
          'The model provider did not respond within the request timeout. Try the research again later.',
        toast: 'Run failed. See the suggested next step below.',
      };
    case 'llm_timeout_unknown':
      return {
        message:
          'The provider may have accepted the request; acceptance and any charge are unconfirmed. The run was not retried automatically. Restarting or resuming may repeat provider work.',
        toast: 'Run failed. See the suggested next step below.',
      };
    default:
      return null;
  }
}
