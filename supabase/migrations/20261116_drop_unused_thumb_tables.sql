-- Rimozione tabelle del progetto estraneo "generatore thumbnail YouTube" (mai usate dalla webapp GDC)
drop table if exists public.thumb_capture_jobs, public.thumb_jobs, public.thumb_proposals,
  public.thumb_gallery_images, public.thumb_scripts, public.thumb_videos, public.thumb_clients,
  public.thumb_image_providers, public.thumb_text_providers;
