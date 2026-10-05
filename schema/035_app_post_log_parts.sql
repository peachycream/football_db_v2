-- Phase 11: a post is now SEVERAL Discord messages (cover image, position-board image, the written breakdown), so the log
-- tracks the parts. A failure part-way leaves parts_posted = how many were delivered; the next run RESUMES from there, so
-- the first message is never posted twice. A row written before this migration (one message) has parts_total NULL and is
-- read as complete. message_ids is every Discord message id, comma separated, in order (for deleting a wrong post).
ALTER TABLE app_post_log ADD COLUMN parts_total INTEGER;
ALTER TABLE app_post_log ADD COLUMN parts_posted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app_post_log ADD COLUMN message_ids TEXT;
