-- Reels Fabrikası → Supabase (bir kez: Supabase paneli → SQL Editor → çalıştır)
-- Yükleme yalnızca bu bilgisayardaki service_role anahtarıyla yapılır; tablo ve depo herkese kapalıdır (RLS).
create table if not exists public.reels_videos (
  job_id         text primary key,
  title          text,
  category       text,
  video_path     text,          -- depo yolu: reels/<job_id>/<dosya>.mp4
  thumbnail_path text,
  caption        text,
  meta           jsonb default '{}'::jsonb,   -- kaynak (görselden video / fabrika), sesler, klipler, tasarım
  created_at     timestamptz default now()
);
alter table public.reels_videos enable row level security;   -- politika yok: yalnızca service_role erişir

insert into storage.buckets (id, name, public) values ('reels', 'reels', false)
on conflict (id) do nothing;
