import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiAssistantPanel } from "@/features/ai/components/ai-assistant-panel";
import { renderWithQueryClient } from "@/test/test-utils";
import type { AiInsight } from "@/types/ai";

vi.mock("@/services/ai-service", () => ({
  aiService: {
    askAssistant: vi.fn(),
  },
}));

import { aiService } from "@/services/ai-service";

const askAssistantMock = vi.mocked(aiService.askAssistant);

function buildInsight(overrides: Partial<AiInsight> = {}): AiInsight {
  return {
    text: "You have 2 open requests.",
    generated_by: "openai:gpt-test",
    is_fallback: false,
    cached: false,
    generated_at: "2026-07-26T00:00:00Z",
    ...overrides,
  };
}

describe("AiAssistantPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows placeholder guidance before any question is asked", () => {
    renderWithQueryClient(<AiAssistantPanel />);

    expect(screen.getByText(/Ask a question about your dashboard/i)).toBeInTheDocument();
  });

  it("sends a question and renders the reply", async () => {
    askAssistantMock.mockResolvedValue(buildInsight());
    const user = userEvent.setup();

    renderWithQueryClient(<AiAssistantPanel />);
    await user.type(
      screen.getByLabelText("Ask the AI assistant"),
      "How many requests are open?",
    );
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("How many requests are open?")).toBeInTheDocument();
    expect(await screen.findByText("You have 2 open requests.")).toBeInTheDocument();
    expect(askAssistantMock).toHaveBeenCalledWith({
      question: "How many requests are open?",
      history: [],
    });
  });

  it("renders a fallback caption when the reply is a non-AI fallback", async () => {
    askAssistantMock.mockResolvedValue(buildInsight({ is_fallback: true, generated_by: null }));
    const user = userEvent.setup();

    renderWithQueryClient(<AiAssistantPanel />);
    await user.type(screen.getByLabelText("Ask the AI assistant"), "question");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/AI unavailable/i)).toBeInTheDocument();
  });

  it("resends prior turns as history on the next question", async () => {
    askAssistantMock.mockResolvedValue(buildInsight());
    const user = userEvent.setup();

    renderWithQueryClient(<AiAssistantPanel />);
    await user.type(screen.getByLabelText("Ask the AI assistant"), "first question");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("You have 2 open requests.");

    await user.type(screen.getByLabelText("Ask the AI assistant"), "second question");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() =>
      expect(askAssistantMock).toHaveBeenLastCalledWith({
        question: "second question",
        history: [
          { role: "user", content: "first question" },
          { role: "assistant", content: "You have 2 open requests." },
        ],
      }),
    );
  });

  it("does not send a blank question", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<AiAssistantPanel />);

    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(askAssistantMock).not.toHaveBeenCalled();
  });
});
