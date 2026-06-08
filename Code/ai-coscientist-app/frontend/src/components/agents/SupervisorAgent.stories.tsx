import type { Meta, StoryObj } from "@storybook/react";
import { SupervisorAgent } from "./SupervisorAgent";
import { mockAgentOutputs } from "@/mocks/mockData";

const meta: Meta<typeof SupervisorAgent> = {
  title: "Agents/SupervisorAgent",
  component: SupervisorAgent,
  parameters: {
    layout: "padded",
  },
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof SupervisorAgent>;

export const Default: Story = {
  args: {
    output: mockAgentOutputs[0],
  },
};
