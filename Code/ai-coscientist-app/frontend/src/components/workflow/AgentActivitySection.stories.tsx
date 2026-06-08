import type { Meta, StoryObj } from "@storybook/react";
import { AgentActivitySection } from "./AgentActivitySection";
import { mockAgentOutputs } from "@/mocks/mockData";

const meta: Meta<typeof AgentActivitySection> = {
  title: "Workflow/AgentActivitySection",
  component: AgentActivitySection,
  parameters: {
    layout: "padded",
  },
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof AgentActivitySection>;

export const InitialGeneration: Story = {
  args: {
    agentOutputs: mockAgentOutputs,
  },
};

export const Empty: Story = {
  args: {
    agentOutputs: [],
  },
};
