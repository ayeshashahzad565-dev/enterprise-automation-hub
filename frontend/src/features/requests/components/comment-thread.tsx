"use client";

import { formatDistanceToNow } from "date-fns";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/features/profile/hooks/use-current-user";
import { useAuth } from "@/providers/auth-provider";
import type { Comment } from "@/types/comment";

export function CommentThread({
  comments,
  onRemove,
}: {
  comments: Comment[];
  onRemove: (commentId: string) => void;
}) {
  const { user } = useAuth();
  const { data: profile } = useCurrentUser();
  const isAdmin = profile?.role === "admin";

  if (comments.length === 0) {
    return <p className="text-sm text-muted-foreground">No comments yet.</p>;
  }

  return (
    <ul className="space-y-4">
      {comments.map((comment) => {
        const isRemoved = Boolean(comment.deleted_at);
        const isMine = comment.author_id === user?.id;
        return (
          <li key={comment.id} className="flex items-start justify-between gap-2">
            <div className="space-y-1">
              <p className="text-sm font-medium">
                {isMine ? "You" : `${comment.author_id.slice(0, 8)}…`}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(comment.created_at), { addSuffix: true })}
              </p>
              <p className={isRemoved ? "text-sm text-muted-foreground italic" : "text-sm"}>
                {isRemoved ? "This comment was removed." : comment.body}
              </p>
            </div>
            {isAdmin && !isRemoved && (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Remove comment"
                onClick={() => onRemove(comment.id)}
              >
                <Trash2 className="size-4" />
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
