-- The Lineup: accounts, "going", and connect requests.
-- Paste this whole file into Supabase -> SQL Editor -> Run. Safe to re-run.
--
-- Privacy rules this enforces (in the database, not just the UI):
--   * Anyone can see HOW MANY people are going. Nobody anonymous sees WHO.
--   * You only see who's going to an event if you're signed in AND going too.
--   * Attendee lists show first name + last initial, role, experience. Never email.
--   * Company is optional, off by default, and only shown to people you've connected with.
--   * Connect requests open 7 days before an event and close 1 day after it.
--   * Max 5 outgoing requests per person per event. One request per pair per event.
--   * Emails are only revealed after BOTH people say yes.
--   * Blocking hides you from each other everywhere and kills pending requests.
--   * Deleting your account wipes everything (cascade).

create extension if not exists pgcrypto;

-- ---------- events (written only by the scraper with the service key) ----------
create table if not exists public.events (
  id          text primary key,           -- same id as events.json
  title       text not null,
  starts_at   timestamptz not null,
  state       text,
  city        text,
  updated_at  timestamptz not null default now()
);

-- ---------- profiles ----------
create table if not exists public.profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  first_name    text not null check (char_length(first_name) between 1 and 40),
  last_name     text not null check (char_length(last_name) between 1 and 60),
  role          text not null check (role in (
                  'Student','IT Support / Help Desk','SOC / Analyst','GRC / Audit',
                  'Security Engineer','Pentest / Red Team','Cloud / DevOps','Network Engineer',
                  'Software / AI Engineer','Data / ML','Manager / Leader','Recruiter','Founder','Other')),
  experience    text not null check (experience in ('Student','0-2 years','3-5 years','6-10 years','10+ years')),
  company       text check (company is null or char_length(company) <= 80),
  show_company  boolean not null default false,
  is_adult      boolean not null check (is_adult),      -- 18+ checkbox; required
  accepted_terms_at timestamptz not null default now(),
  created_at    timestamptz not null default now()
);

-- ---------- going ----------
create table if not exists public.rsvps (
  user_id    uuid not null references public.profiles(id) on delete cascade,
  event_id   text not null references public.events(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, event_id)
);
create index if not exists rsvps_event_idx on public.rsvps(event_id);

-- ---------- blocks & reports ----------
create table if not exists public.blocks (
  blocker uuid not null references public.profiles(id) on delete cascade,
  blocked uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker, blocked),
  check (blocker <> blocked)
);

create table if not exists public.reports (
  id         uuid primary key default gen_random_uuid(),
  reporter   uuid not null references public.profiles(id) on delete cascade,
  reported   uuid not null references public.profiles(id) on delete cascade,
  event_id   text references public.events(id) on delete set null,
  reason     text not null check (char_length(reason) between 3 and 1000),
  created_at timestamptz not null default now()
);

-- ---------- connect requests ----------
create table if not exists public.connections (
  id           uuid primary key default gen_random_uuid(),
  event_id     text not null references public.events(id) on delete cascade,
  from_user    uuid not null references public.profiles(id) on delete cascade,
  to_user      uuid not null references public.profiles(id) on delete cascade,
  note         text check (note is null or char_length(note) <= 200),
  status       text not null default 'pending' check (status in ('pending','accepted','declined')),
  created_at   timestamptz not null default now(),
  responded_at timestamptz,
  unique (event_id, from_user, to_user),
  check (from_user <> to_user)
);
create index if not exists conn_to_idx on public.connections(to_user, status);

-- ---------- helpers ----------
create or replace function public.is_blocked(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from blocks where (blocker = a and blocked = b) or (blocker = b and blocked = a));
$$;

create or replace function public.is_going(u uuid, e text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from rsvps where user_id = u and event_id = e);
$$;

-- Rules checked on every new connect request. The UI checks too, but this is the real gate.
create or replace function public.check_connection() returns trigger
language plpgsql security definer set search_path = public as $$
declare s timestamptz;
begin
  if new.from_user <> auth.uid() then raise exception 'You can only send requests as yourself'; end if;
  select starts_at into s from events where id = new.event_id;
  if s is null then raise exception 'Unknown event'; end if;
  if now() < s - interval '7 days' then raise exception 'Connect opens 7 days before the event'; end if;
  if now() > s + interval '1 day' then raise exception 'Connect closed for this event'; end if;
  if not is_going(new.from_user, new.event_id) or not is_going(new.to_user, new.event_id) then
    raise exception 'You both need to be going'; end if;
  if is_blocked(new.from_user, new.to_user) then raise exception 'Not available'; end if;
  if (select count(*) from connections where event_id = new.event_id and from_user = new.from_user) >= 5 then
    raise exception 'Max 5 connect requests per event'; end if;
  if exists (select 1 from connections where event_id = new.event_id and from_user = new.to_user and to_user = new.from_user) then
    raise exception 'They already sent you a request, check your inbox'; end if;
  new.status := 'pending'; new.responded_at := null;
  return new;
end $$;
drop trigger if exists connections_check on public.connections;
create trigger connections_check before insert on public.connections
  for each row execute function public.check_connection();

-- Only the recipient can answer, only once, only accept/decline.
create or replace function public.check_connection_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if old.to_user <> auth.uid() then raise exception 'Only the recipient can respond'; end if;
  if old.status <> 'pending' then raise exception 'Already answered'; end if;
  if new.status not in ('accepted','declined') then raise exception 'Bad status'; end if;
  if new.event_id <> old.event_id or new.from_user <> old.from_user or new.to_user <> old.to_user
     or coalesce(new.note,'') <> coalesce(old.note,'') then raise exception 'Only status can change'; end if;
  new.responded_at := now();
  return new;
end $$;
drop trigger if exists connections_update_check on public.connections;
create trigger connections_update_check before update on public.connections
  for each row execute function public.check_connection_update();

-- Blocking someone deletes any pending requests between you.
create or replace function public.after_block() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  delete from connections where status = 'pending'
    and ((from_user = new.blocker and to_user = new.blocked) or (from_user = new.blocked and to_user = new.blocker));
  return new;
end $$;
drop trigger if exists blocks_after on public.blocks;
create trigger blocks_after after insert on public.blocks for each row execute function public.after_block();

-- ---------- row level security ----------
alter table public.events      enable row level security;
alter table public.profiles    enable row level security;
alter table public.rsvps       enable row level security;
alter table public.blocks      enable row level security;
alter table public.reports     enable row level security;
alter table public.connections enable row level security;

drop policy if exists events_read on public.events;
create policy events_read on public.events for select using (true);

drop policy if exists profiles_own on public.profiles;
create policy profiles_own on public.profiles for all
  using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists rsvps_own on public.rsvps;
create policy rsvps_own on public.rsvps for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists blocks_own on public.blocks;
create policy blocks_own on public.blocks for all
  using (blocker = auth.uid()) with check (blocker = auth.uid());

drop policy if exists reports_insert on public.reports;
create policy reports_insert on public.reports for insert with check (reporter = auth.uid());
-- reports are read by Josh in the Supabase dashboard only.

drop policy if exists conn_read on public.connections;
create policy conn_read on public.connections for select
  using (from_user = auth.uid() or to_user = auth.uid());
drop policy if exists conn_insert on public.connections;
create policy conn_insert on public.connections for insert with check (from_user = auth.uid());
drop policy if exists conn_update on public.connections;
create policy conn_update on public.connections for update using (to_user = auth.uid());
drop policy if exists conn_delete on public.connections;
create policy conn_delete on public.connections for delete using (from_user = auth.uid() and status = 'pending');

-- ---------- what the site calls ----------

-- Public: going counts for a batch of events. Numbers only, no names.
create or replace function public.going_counts(ids text[])
returns table (event_id text, going bigint)
language sql stable security definer set search_path = public as $$
  select r.event_id, count(*) from rsvps r where r.event_id = any(ids) group by r.event_id;
$$;

-- Signed-in AND going: who else is going. Minimal fields. Blocked people hidden both ways.
create or replace function public.attendees(e text)
returns table (user_id uuid, first_name text, last_initial text, role text, experience text, connect_status text)
language sql stable security definer set search_path = public as $$
  select p.id, p.first_name, left(p.last_name, 1), p.role, p.experience,
         (select c.status || case when c.from_user = auth.uid() then ':sent' else ':received' end
            from connections c
           where c.event_id = e
             and ((c.from_user = auth.uid() and c.to_user = p.id) or (c.to_user = auth.uid() and c.from_user = p.id))
           limit 1)
    from rsvps r join profiles p on p.id = r.user_id
   where r.event_id = e
     and auth.uid() is not null
     and is_going(auth.uid(), e)
     and p.id <> auth.uid()
     and not is_blocked(auth.uid(), p.id)
   order by r.created_at;
$$;

-- My inbox: pending requests sent to me (name + role only, no email).
create or replace function public.my_requests()
returns table (id uuid, event_id text, event_title text, starts_at timestamptz,
               first_name text, last_initial text, role text, experience text, note text, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select c.id, c.event_id, ev.title, ev.starts_at, p.first_name, left(p.last_name,1), p.role, p.experience, c.note, c.created_at
    from connections c join profiles p on p.id = c.from_user join events ev on ev.id = c.event_id
   where c.to_user = auth.uid() and c.status = 'pending' and not is_blocked(auth.uid(), c.from_user)
   order by c.created_at desc;
$$;

-- My connections: ONLY mutual accepts. This is the only place an email ever comes out.
create or replace function public.my_connections()
returns table (event_title text, starts_at timestamptz, first_name text, last_name text,
               role text, company text, email text, connected_at timestamptz)
language sql stable security definer set search_path = public, auth as $$
  select ev.title, ev.starts_at, p.first_name, p.last_name, p.role,
         case when p.show_company then p.company end, u.email::text, c.responded_at
    from connections c
    join events ev on ev.id = c.event_id
    join profiles p on p.id = case when c.from_user = auth.uid() then c.to_user else c.from_user end
    join auth.users u on u.id = p.id
   where c.status = 'accepted'
     and (c.from_user = auth.uid() or c.to_user = auth.uid())
     and not is_blocked(auth.uid(), p.id)
   order by c.responded_at desc;
$$;

-- Delete my account and everything tied to it.
create or replace function public.delete_me() returns void
language sql security definer set search_path = public, auth as $$
  delete from auth.users where id = auth.uid();
$$;

-- Lock down: the anon key can only hit what the site needs.
revoke all on function public.attendees(text), public.my_requests(), public.my_connections(), public.delete_me() from public, anon;
grant execute on function public.attendees(text), public.my_requests(), public.my_connections(), public.delete_me() to authenticated;
grant execute on function public.going_counts(text[]) to anon, authenticated;
revoke all on function public.is_blocked(uuid,uuid), public.is_going(uuid,text) from public, anon;

-- Table access for the site (works whether or not "grant API access automatically" was on).
-- Row level security above still decides which ROWS each person can touch.
grant usage on schema public to anon, authenticated;
grant select on public.events to anon, authenticated;
grant select, insert, update, delete on public.profiles, public.rsvps, public.blocks to authenticated;
grant insert on public.reports to authenticated;
grant select, insert, update, delete on public.connections to authenticated;
revoke all on public.profiles, public.rsvps, public.blocks, public.reports, public.connections from anon;
