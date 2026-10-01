ALTER TABLE merchant_posts
  DROP CONSTRAINT IF EXISTS merchant_posts_position_check;

ALTER TABLE merchant_posts
  ADD CONSTRAINT merchant_posts_position_check
  CHECK (position BETWEEN 1 AND 500);
