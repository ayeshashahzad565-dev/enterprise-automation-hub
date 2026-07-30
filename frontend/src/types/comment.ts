export interface Comment {
  id: string;
  request_id: string;
  author_id: string;
  parent_comment_id: string | null;
  body: string;
  deleted_at: string | null;
  deleted_by: string | null;
  created_at: string;
}

export interface CommentCreateInput {
  body: string;
  parent_comment_id?: string | null;
}
