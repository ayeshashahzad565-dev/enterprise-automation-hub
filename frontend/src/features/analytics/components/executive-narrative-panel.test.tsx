import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExecutiveNarrativePanel } from "@/features/analytics/components/executive-narrative-panel";

describe("ExecutiveNarrativePanel", () => {
  it("shows a loading state and no content while loading", () => {
    render(<ExecutiveNarrativePanel narrative={undefined} isLoading isError={false} />);

    expect(screen.getByText("Executive summary")).toBeInTheDocument();
    expect(screen.queryByText(/couldn't load/i)).not.toBeInTheDocument();
  });

  it("renders the narrative once loaded", () => {
    render(
      <ExecutiveNarrativePanel narrative="Requests are trending down." isLoading={false} isError={false} />,
    );

    expect(screen.getByText("Requests are trending down.")).toBeInTheDocument();
  });

  it("shows an error state and retries on click instead of silently disappearing", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(
      <ExecutiveNarrativePanel narrative={undefined} isLoading={false} isError onRetry={onRetry} />,
    );

    expect(screen.getByText("Couldn't load the executive summary.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
