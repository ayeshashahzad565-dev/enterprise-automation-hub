"use client";

import { SendHorizontal } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useState } from "react";

import { Caption, SectionHeading } from "@/components/patterns/typography";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { AiBadge } from "@/features/ai/components/ai-badge";
import { useAskAssistant } from "@/features/ai/hooks/use-ask-assistant";
import type { AiChatTurn } from "@/types/ai";
import { cn } from "@/lib/utils";

interface DisplayedTurn extends AiChatTurn {
  id: number;
  isFallback?: boolean;
}

let nextTurnId = 0;

/** A non-streaming (request/response) chat panel grounded in the caller's
 * own dashboard data — see `AiInsightService.ask_assistant`'s docstring
 * for why this is deliberately not agentic/tool-using and not streamed.
 * Conversation state lives client-side only; each call resends the prior
 * turns as `history` (no server-side persistence). */
export function AiAssistantPanel({ className }: { className?: string }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<DisplayedTurn[]>([]);
  const askAssistant = useAskAssistant();

  function submitQuestion() {
    const trimmed = question.trim();
    if (!trimmed || askAssistant.isPending) return;

    const history = turns.map(({ role, content }) => ({ role, content }));
    setTurns((prev) => [...prev, { id: nextTurnId++, role: "user", content: trimmed }]);
    setQuestion("");

    askAssistant.mutate(
      { question: trimmed, history },
      {
        onSuccess: (insight) => {
          setTurns((prev) => [
            ...prev,
            {
              id: nextTurnId++,
              role: "assistant",
              content: insight.text,
              isFallback: insight.is_fallback,
            },
          ]);
        },
        onError: () => {
          setTurns((prev) => [
            ...prev,
            {
              id: nextTurnId++,
              role: "assistant",
              content: "Something went wrong answering that. Please try again.",
              isFallback: true,
            },
          ]);
        },
      },
    );
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submitQuestion();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitQuestion();
    }
  }

  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <SectionHeading>Ask about your data</SectionHeading>
        <AiBadge />
      </CardHeader>
      <CardContent className="space-y-4">
        {turns.length === 0 && (
          <Caption>
            Ask a question about your dashboard — e.g. &ldquo;How many approvals are
            overdue?&rdquo;
          </Caption>
        )}
        {turns.length > 0 && (
          <ul className="space-y-3" aria-live="polite">
            {turns.map((turn) => (
              <li
                key={turn.id}
                className={cn(
                  "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                  turn.role === "user"
                    ? "ml-auto bg-primary text-primary-foreground"
                    : "mr-auto bg-muted text-foreground",
                )}
              >
                <p className="whitespace-pre-line">{turn.content}</p>
                {turn.isFallback && (
                  <Caption className="mt-1">AI unavailable — fallback response.</Caption>
                )}
              </li>
            ))}
          </ul>
        )}
        {askAssistant.isPending && <Caption>Thinking…</Caption>}
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <Textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question..."
            rows={2}
            aria-label="Ask the AI assistant"
          />
          <Button
            type="submit"
            size="icon"
            aria-label="Ask"
            disabled={askAssistant.isPending || !question.trim()}
          >
            <SendHorizontal className="size-4" />
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
