// node execution order for each iteration type
// matches actual open-coscientist workflow
export const NODE_ORDER_INITIAL = [
  "supervisor",
  "literature_review",
  "generate",
  "reflection",
  "review",
  "ranking",
];

export const NODE_ORDER_ITERATION = ["meta_review", "evolve", "review", "ranking", "proximity"];

// progress percentages within a single iteration
export const NODE_PROGRESS_INITIAL: Record<string, number> = {
  supervisor: 10,
  literature_review: 20,
  generate: 40,
  reflection: 50,
  review: 70,
  ranking: 95,
};

export const NODE_PROGRESS_ITERATION: Record<string, number> = {
  meta_review: 15,
  evolve: 30,
  review: 60,
  ranking: 85,
  proximity: 95,
};

export interface ProgressCalculationResult {
  overallProgress: number;
  progressMessage: string;
  nextNode: string | null;
}

/**
 * calculate overall progress across all iterations
 *
 * @param nodeName - current node being processed
 * @param currentIteration - current iteration (0 = initial, 1+ = iterations)
 * @param maxIterations - total refinement iterations (0 = no iterations, 1 = 1 iteration, etc.)
 * @returns overall progress percentage (0-100)
 */
export function calculateOverallProgress(
  nodeName: string,
  currentIteration: number,
  maxIterations: number
): ProgressCalculationResult {
  // total iterations = initial (iteration 0) + refinement iterations
  const totalIterations = maxIterations + 1;

  // determine if we're in initial or iteration phase
  const isInitial = currentIteration === 0;
  const nodeOrder = isInitial ? NODE_ORDER_INITIAL : NODE_ORDER_ITERATION;
  const nodeProgress = isInitial ? NODE_PROGRESS_INITIAL : NODE_PROGRESS_ITERATION;

  // get progress within current iteration
  const progressInIteration = nodeProgress[nodeName] || 50;

  // calculate overall progress
  // formula: (completed iterations / total iterations) * 100 + (current iteration progress / total iterations)
  const completedIterations = currentIteration;
  const iterationWeight = 100 / totalIterations;
  const overallProgress =
    completedIterations * iterationWeight + (progressInIteration * iterationWeight) / 100;

  // determine next node
  const currentNodeIndex = nodeOrder.indexOf(nodeName);
  let nextNode: string | null = null;

  if (currentNodeIndex !== -1 && currentNodeIndex < nodeOrder.length - 1) {
    // next node in same iteration
    nextNode = nodeOrder[currentNodeIndex + 1];
  } else if (currentIteration < maxIterations) {
    // next node is first node of next iteration
    nextNode = NODE_ORDER_ITERATION[0];
  }

  // create progress message
  const nodeNameFormatted = nodeName.charAt(0).toUpperCase() + nodeName.slice(1).replace("_", " ");
  let message = `Processing ${nodeNameFormatted}...`;

  // add "Next: ..." if we know the next node
  if (nextNode) {
    const nextNodeFormatted =
      nextNode.charAt(0).toUpperCase() + nextNode.slice(1).replace("_", " ");
    message = `${nodeNameFormatted} complete. Next: ${nextNodeFormatted}...`;
  }

  return {
    overallProgress: Math.min(Math.max(overallProgress, 0), 100),
    progressMessage: message,
    nextNode,
  };
}

/**
 * get the next expected node based on current node and iteration
 * useful for predictive UI updates
 */
export function getNextNode(
  currentNode: string,
  currentIteration: number,
  maxIterations: number
): string | null {
  const isInitial = currentIteration === 0;
  const nodeOrder = isInitial ? NODE_ORDER_INITIAL : NODE_ORDER_ITERATION;

  const currentNodeIndex = nodeOrder.indexOf(currentNode);

  if (currentNodeIndex !== -1 && currentNodeIndex < nodeOrder.length - 1) {
    return nodeOrder[currentNodeIndex + 1];
  } else if (currentIteration < maxIterations) {
    return NODE_ORDER_ITERATION[0];
  }

  return null;
}

/**
 * format node name for display
 */
export function formatNodeName(nodeName: string): string {
  return nodeName
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
