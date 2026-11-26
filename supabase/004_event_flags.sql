-- "Something wrong with this listing?" reports. Anyone can send one (no account needed); only Josh reads them.
create table if not exists public.event_flags (
  id         uuid primary key default gen_random_uuid(),
  event_id   text not null check (char_length(event_id) between 4 and 40),
  reason     text not null check (reason in ('wrong_place','online','cancelled','not_cyber','duplicate','wrong_time','full','other')),
  note       text check (note is null or char_length(note) <= 300),
  created_at timestamptz not null default now()
);
alter table public.event_flags enable row level security;
drop policy if exists flags_insert on public.event_flags;
create policy flags_insert on public.event_flags for insert to anon, authenticated with check (true);
grant insert on public.event_flags to anon, authenticated;
revoke select, update, delete on public.event_flags from anon, authenticated;

-- light spam guard: at most 30 flags a minute site-wide
create or replace function public.flags_rate_limit() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from event_flags where created_at > now() - interval '1 minute') >= 30 then
    raise exception 'Too many reports right now, try again in a minute';
  end if;
  return new;
end $$;
drop trigger if exists flags_rl on public.event_flags;
create trigger flags_rl before insert on public.event_flags for each row execute function public.flags_rate_limit();

-- for the weekly coverage email (robot only)
create or replace function public.recent_flags(days int default 7)
returns table (event_id text, reason text, note text, n bigint, last_at timestamptz)
language sql stable security definer set search_path = public as $$
  select event_id, reason, max(note), count(*), max(created_at) from event_flags
   where created_at > now() - make_interval(days => days) group by event_id, reason order by count(*) desc;
$$;
revoke all on function public.recent_flags(int) from public, anon, authenticated;
grant execute on function public.recent_flags(int) to service_role;
