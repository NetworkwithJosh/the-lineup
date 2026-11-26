-- The Lineup, step 2: home state, email opt-ins, and what the email robot needs.
-- Safe to re-run.

alter table public.profiles
  add column if not exists home_state    text check (home_state is null or home_state ~ '^[A-Z]{2}$'),
  add column if not exists weekly_digest boolean not null default true,
  add column if not exists notify        boolean not null default true,
  add column if not exists unsub_token   uuid not null default gen_random_uuid();
create unique index if not exists profiles_unsub_idx on public.profiles(unsub_token);

alter table public.connections
  add column if not exists notified_at        timestamptz,   -- recipient told "X wants to connect"
  add column if not exists accept_notified_at timestamptz;   -- sender told "X accepted"

-- ---------- robot-only functions (service key only, never the website) ----------

-- Connect emails waiting to go out.
create or replace function public.pending_connect_notices()
returns table (id uuid, kind text, to_email text, to_first text, unsub_token uuid,
               other_first text, other_last text, other_role text, other_experience text, other_email text,
               event_title text, starts_at timestamptz)
language sql stable security definer set search_path = public, auth as $$
  -- new requests -> tell the recipient (no email shared yet)
  select c.id, 'request', u.email::text, p.first_name, p.unsub_token,
         f.first_name, left(f.last_name, 1), f.role, f.experience, null::text, ev.title, ev.starts_at
    from connections c
    join profiles p on p.id = c.to_user join auth.users u on u.id = p.id
    join profiles f on f.id = c.from_user join events ev on ev.id = c.event_id
   where c.status = 'pending' and c.notified_at is null and p.notify
     and c.created_at > now() - interval '3 days'
     and not is_blocked(c.from_user, c.to_user)
  union all
  -- accepted -> tell the sender, with the other person's email (both said yes)
  select c.id, 'accepted', u.email::text, p.first_name, p.unsub_token,
         t.first_name, t.last_name, t.role, t.experience, tu.email::text, ev.title, ev.starts_at
    from connections c
    join profiles p on p.id = c.from_user join auth.users u on u.id = p.id
    join profiles t on t.id = c.to_user join auth.users tu on tu.id = t.id
    join events ev on ev.id = c.event_id
   where c.status = 'accepted' and c.accept_notified_at is null and p.notify
     and c.responded_at > now() - interval '3 days'
     and not is_blocked(c.from_user, c.to_user);
$$;

create or replace function public.mark_connect_notices(ids uuid[], kind text) returns void
language sql security definer set search_path = public as $$
  update connections set notified_at = now() where kind = 'request' and id = any(ids);
  update connections set accept_notified_at = now() where kind = 'accepted' and id = any(ids);
$$;

-- Who gets the Monday email.
create or replace function public.digest_recipients()
returns table (email text, first_name text, home_state text, unsub_token uuid)
language sql stable security definer set search_path = public, auth as $$
  select u.email::text, p.first_name, p.home_state, p.unsub_token
    from profiles p join auth.users u on u.id = p.id
   where p.weekly_digest and p.home_state is not null and u.email_confirmed_at is not null;
$$;

-- One-click unsubscribe from an email link (no sign-in needed; the token is the key).
create or replace function public.unsubscribe(token uuid, what text default 'all') returns boolean
language plpgsql security definer set search_path = public as $$
begin
  update profiles set
    weekly_digest = case when what in ('all','digest') then false else weekly_digest end,
    notify        = case when what in ('all','notify') then false else notify end
  where unsub_token = token;
  return found;
end $$;

revoke all on function public.pending_connect_notices(), public.mark_connect_notices(uuid[], text),
  public.digest_recipients() from public, anon, authenticated;
grant execute on function public.pending_connect_notices(), public.mark_connect_notices(uuid[], text),
  public.digest_recipients() to service_role;
revoke all on function public.unsubscribe(uuid, text) from public;
grant execute on function public.unsubscribe(uuid, text) to anon, authenticated;
