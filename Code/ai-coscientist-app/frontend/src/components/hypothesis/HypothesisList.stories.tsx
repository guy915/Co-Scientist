import type { Meta, StoryObj } from "@storybook/react";
import { mockHypotheses } from "@/mocks/mockData";
import { HypothesisList } from "./HypothesisList";

const meta: Meta<typeof HypothesisList> = {
  title: "Hypothesis/HypothesisList",
  component: HypothesisList,
  parameters: {
    layout: "padded",
  },
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof HypothesisList>;

export const Default: Story = {
  args: {
    hypotheses: mockHypotheses,
    researchGoal: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
    executionTime: 123.5,
    metrics: {
      llm_calls: 45,
      total_tokens: 125430,
      cache_hit_rate: 0.23,
    },
  },
};

export const SingleHypothesis: Story = {
  args: {
    hypotheses: [mockHypotheses[0]],
    researchGoal: "Simple research question",
    executionTime: 45.2,
  },
};

export const NoMetrics: Story = {
  args: {
    hypotheses: mockHypotheses,
    researchGoal: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
  },
};
