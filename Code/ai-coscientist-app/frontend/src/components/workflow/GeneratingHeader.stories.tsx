import type { Meta, StoryObj } from "@storybook/react";
import { GeneratingHeader } from "./GeneratingHeader";

const meta: Meta<typeof GeneratingHeader> = {
  title: "Workflow/GeneratingHeader",
  component: GeneratingHeader,
  parameters: {
    layout: "padded",
  },
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof GeneratingHeader>;

export const Starting: Story = {
  args: {
    researchGoal: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
    progress: 5,
    progressMessage: "Starting workflow...",
    onCancel: () => alert("Cancelled"),
  },
};

export const GeneratingHypotheses: Story = {
  args: {
    researchGoal: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
    progress: 25,
    progressMessage: "Generating initial hypotheses...",
    onCancel: () => alert("Cancelled"),
  },
};

export const ReviewingHypotheses: Story = {
  args: {
    researchGoal: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
    progress: 50,
    progressMessage: "Reviewing 5 hypotheses...",
    onCancel: () => alert("Cancelled"),
  },
};

export const RankingPhase: Story = {
  args: {
    researchGoal: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
    progress: 75,
    progressMessage: "Running ranking tournament selection...",
    onCancel: () => alert("Cancelled"),
  },
};

export const NearCompletion: Story = {
  args: {
    researchGoal: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
    progress: 95,
    progressMessage: "Finalizing results...",
    onCancel: () => alert("Cancelled"),
  },
};
