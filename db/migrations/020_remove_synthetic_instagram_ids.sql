UPDATE merchants SET instagram_id=NULL
WHERE left(instagram_id,7)='import_' OR left(instagram_id,8)='catalog_';
