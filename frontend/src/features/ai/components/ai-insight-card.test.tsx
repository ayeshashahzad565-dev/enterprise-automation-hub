import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AiInsightCard } from "@/features/ai/components/ai-insight-card";
import type { AiInsight } from "@/types/ai";

function buildInsight(overrides: Partial<AiInsight> = {}): AiInsight {
  return {
    text: "This request is for a new laptop.",
    generated_by: "openai:gpt-test",
    is_fallback: false,
    cached: false,
    generated_at: "2026-07-26T00:00:00Z",
    ...overrides,
  };
}

describe("AiInsightCard", () => {
  it("shows a loading state and no content while loading", () => {
    render(
      <AiInsightCard title="AI summary" data={undefined} isLoading isError={false} />,
    );

    expect(screen.getByText("AI summary")).toBeInTheDocument();
    expect(screen.queryByText(/laptop/i)).not.toBeInTheDocument();
  });

  it("renders the insight text and an AI badge for genuine AI content", () => {
    render(
      <AiInsightCard
        title="AI summary"
        data={buildInsight()}
        isLoading={false}
        isError={false}
      />,
    );

    expect(screen.getByText("This request is for a new laptop.")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("shows a fallback caption instead of the AI badge when is_fallback is true", () => {
    render(
      <AiInsightCard
        title="AI summary"
        data={buildInsight({ is_fallback: true, generated_by: null })}
        isLoading={false}
        isError={false}
      />,
    );

    expect(screen.getByText(/AI unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText("AI")).not.toBeInTheDocument();
  });

  it("does not show a Show more toggle for a short insight", () => {
    render(
      <AiInsightCard title="AI summary" data={buildInsight()} isLoading={false} isError={false} />,
    );

    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("clamps a long insight behind a Show more/Show less toggle", async () => {
    const user = userEvent.setup();
    const longText = "This is a long AI-generated summary sentence. ".repeat(10).trim();
    render(
      <AiInsightCard
        title="AI summary"
        data={buildInsight({ text: longText })}
        isLoading={false}
        isError={false}
      />,
    );

    const paragraph = screen.getByText(longText);
    expect(paragraph.className).toContain("line-clamp-6");

    await user.click(screen.getByRole("button", { name: "Show more" }));
    expect(paragraph.className).not.toContain("line-clamp-6");
    expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show less" }));
    expect(paragraph.className).toContain("line-clamp-6");
  });

  it("shows an error state and retries on click", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(
      <AiInsightCard
        title="AI summary"
        data={undefined}
        isLoading={false}
        isError
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("Couldn't generate this insight.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
