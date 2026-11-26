-- Monday email: also return which events each person marked going, so the email can lead with them.
drop function if exists public.digest_recipients();
create or replace function public.digest_recipients()
returns table (email text, first_name text, home_state text, unsub_token uuid, going text[])
language sql stable security definer set search_path = public, auth as $$
  select u.email::text, p.first_name, p.home_state, p.unsub_token,
         coalesce((select array_agg(r.event_id) from rsvps r where r.user_id = p.id), '{}')
    from profiles p join auth.users u on u.id = p.id
   where p.weekly_digest and p.home_state is not null and u.email_confirmed_at is not null;
$$;
revoke all on function public.digest_recipients() from public, anon, authenticated;
grant execute on function public.digest_recipients() to service_role;
